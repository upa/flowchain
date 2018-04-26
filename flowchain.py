#!/usr/bin/env python3


import os
import sys
import json

from logging import getLogger, DEBUG, StreamHandler, Formatter
from logging.handlers import SysLogHandler
logger = getLogger(__name__)
logger.setLevel(DEBUG)
stream = StreamHandler()
syslog = SysLogHandler(address = "/dev/log")
syslog.setFormatter(Formatter("flowchain: %(message)s"))
logger.addHandler(stream)
logger.addHandler(syslog)
logger.propagate = False


CONFIG_JSON = os.path.join(os.path.dirname(__file__), 'config.json')


class Function :

    def __init__(self, name, rdtop, rdbot, mark, cgn) :
        self.name = name
        self.rdtop = rdtop
        self.rdbot = rdbot
        self.mark = mark
        self.cgn = cgn
        self.fp = None
        return


class FunctionPool :

    def __init__(self, name) :
        self.name = name
        self.functions = {} # key:fn.name, value:class Function
        self.inter_fp_rd = {} # key: fp.name, value: rd
        self.user_vrf_rd = {} # key: global/private, value:rd
        return


    def add_function(self, fn) :

        if fn.name in self.functions :
            raise RuntimeError('Duplicated Function "%s" in %s',
                               fn.name, self.name)
        self.functions[fn.name] = fn
        fn.fp = self
        return


    def find_function(self, fnname) :

        if fnname in self.functions :
            return self.functions[fnname]
        return None


    def add_inter_fp_rd(self, fpname, rd) :

        if fpname in self.inter_fp_rd :
            raise RuntimeError('Duplicated Inter FP RD "%s" in %s',
                               rd, self.name)
        self.inter_fp_rd[fpname] = rd
        return


    def add_user_vrf_rd(self, vrfname, rd) :

        self.user_vrf_rd[vrfname] = rd
        return
    
class FunctionPools :
    """ just a wrapper class for multiple function pools """

    def __init__(self, fps) :
        """"
        @fps: list of FunctionPool
        """
        self.fps = fps
        return

    def add_fp(self, fp) :
        self.fps.append(fp)
        return

    def find_rd_of_user_vrf(self, vrfname) :

        for fp in self.fps :
            for vn, rd in fp.user_vrf_rd.items() :
                if vn == vrfname :
                    return rd
        return None
            

    def find_function_by_name(self,fnname) :

        for fp in self.fps :
            if fnname in fp.functions :
                return fp.functions[fnname]
        return None

    def find_inter_fp_rd(self, fp_from, fp_to) :

        if not fp_to.name in fp_from.inter_fp_rd :
            return None

        return fp_from.inter_fp_rd[fp_to.name]

    
class Flow :

    def __init__(self, start, chain, prefix, prefix_natted = None) :

        """ 
        @start: user VRF name as a start point
        @chain: list of names of chained Functions
        @prefix: target user prefix for this chain
        @prefix_natted: it is used as the target prefix after CGN function
        """

        self.start = start
        self.chain = chain
        self.prefix = prefix
        self.prefix_natted = prefix_natted
        self.eroutes = [] # list of egress "flow route" for exabgp
        self.iroutes = [] # list of ingress "flow route" for exabgp
        return

    def __eq__(self, other) :
        return (self.chain == other.chain and
                self.prefix == other.prefix and
                self.prefix_natted == other.prefix_natted)

    def __ne__(self, other) :
        return not self.__eq__(other)


    def encode(self, fps) :
        """ @fps: FunctionPools
        Encode the chain of function names into exabgp flow routes

        An ingress flow is composed from folloing Flowspec routes:
        1.
          redirect to the bottom VRF from user vrf (self.start)
        2.
          if the next fuction is in the same FP,
            redirect to bottom VRF of next function from the top of previous
          if the next function is in the different FP,
            redirect to the inter-fp-rd with set mark of the next function.
        3.
          repeat the step 2 to reach the bottom VRF of the last Function

        all flows have the state { match source self.prefix }.
        Note that after cgn == ture Function, use prefix_natted.
        """
        
        flowfmt = ("flow route {{ "
                   + "rd {rd}; "
                   + "match {{ {direct} {prefix}; }} "
                   + "then {{"
                   + "extended-community target:{rd}; "
                   + "{mark} "
                   + "reidrect {redirect};"
                   + "}} }}")

        # Step 1. User VRF to 1st VRF
        user_rd = fps.find_rd_of_user_vrf(self.start)
        next_fn = fps.find_function_by_name(self.chain[0])
        if not user_rd :
            logger.error("Cannot find user VRF for '%s'" % self.start)
            return False
        if not next_fn :
            lgoger.error("Cannot find function '%s'" % self.chain[0])
            return Flase
        
        eroute = flowfmt.format(rd = user_rd, direct = "source",
                                prefix = self.prefix,
                                mark = "", redirect = next_fn.rdbot)
        self.eroutes.append(eroute)

        
        # Step 1.1. Install Flows to All FPs to carry packets from All FPs
        # to Last (1st in Ingress) Function

        
        # Step 2.
        cgn_passed = False
        for x in range(len(self.chain) - 1) :

            prev_fn = fps.find_function_by_name(self.chain[x])
            next_fn = fps.find_function_by_name(self.chain[x + 1])

            if not prev_fn :
                logger.error("Cannot find function '%s' for chain %s:%s" %
                             (prev_fn, self.prefix, self.chain))
                return False
            if not next_fn :
                logger.error("Cannot find function '%s' for chain %s:%s" %
                             (next_fn, self.prefix, self.chain))
                return False
            

            # If CGN passed, switch target prefix to prefix_natted
            if prev_fn.cgn :
                cgn_passed = True
                if not self.prefix_natted :
                    logger.error("NATted prefix is not specified " +
                                 "for chain %s:%s" % (self.prefix, self.chain))
                    return False

            mark_egress = ""
            mark_ingress = ""
            redirect_egress = next_fn.rdbot
            redirect_ingress = prev_fn.rdtop

            # Check is this inter-fp flow ?
            if prev_fn.fp != next_fn.fp :
                # Egress
                inter_fp_rd = fps.find_inter_fp_rd(prev_fn.fp, next_fn.fp)
                if not inter_fp_rd :
                    logger.error("No inter-fp rd from %s to %s" %
                                 (prev_fn.name, next_fn.name))
                    return False
                mark_egress = "mark %d;" % next_fn.mark
                redirect_egress = inter_fp_rd

                # Ingress
                inter_fp_rd = fps.find_inter_fp_rd(next_fn.fp, prev_fn.fp)
                if not inter_fp_rd :
                    logger.error("No inter-fp rd from %s to %s" %
                                 (next_fn.name, prev_fn.name))
                    return False
                mark_ingress = "mark %d;" % prev_fn.mark
                redirect_ingress = inter_fp_rd


            prefix = self.prefix if not cgn_passed else self.prefix_natted

            # Egress Route
            rd = prev_fn.rdtop
            eroute = flowfmt.format(rd = rd, direct = "source",
                                    prefix = prefix,
                                    mark = mark_egress,
                                    redirect = redirect_egress)
            # Ingress Route
            rd = next_fn.rdbot
            iroute = flowfmt.format(rd = rd, direct = "destination",
                                    prefix = prefix,
                                    mark = mark_ingress,
                                    redirect = redirect_ingress)

            self.eroutes.append(eroute)
            self.iroutes.append(iroute)



    def announce(self) :
        # Test
        print("Egress Route")
        print("  \n".join(self.eroutes))
        print("Ingress Route")
        print("  \n".join(self.iroutes))

    def withdraw(self) :
        pass
    


class RoutingInformationBase :

    def __init__(self, fps) :

        self.fps = fps
        self.flows = []
        return

    def find_flow(self, f) :
        
        for flow in self.flows :
            if f == flow :
                return flow
        return None


    def add_flow(self, flow) :

        self.flows.append(flow)
        flow.encode(self.fps)
        flow.announce()
        return


    def delete_flow(self, flow) :
        flow.withdraw()
        self.flows.remove(flow)
        return
        


def load_config(configjson) :

    logger.info("Start to load config file %s" % configjson)

    fps = []

    with open(configjson, 'r') as f :
        cfg = json.load(f)

    for fpname, v in cfg.items() :
        logger.info("Load Function Pool %s" % fpname)

        fp = FunctionPool(fpname)

        for f in v["function"] :
            logger.info("Add Function %s to %s" % (f["name"], fpname))

            fn = Function(f["name"], f["rd-top"], f["rd-bottom"], f["mark"],
                          f["cgn"])
            fp.add_function(fn)

        for fpname, rd in v["inter-fp-rd"].items() :
            fp.add_inter_fp_rd(fpname, rd)
            
        for vrfname, rd in v["user-vrf-rd"].items() :
            fp.add_user_vrf_rd(vrfname, rd)
        
        fps.append(fp)

    return fps


def main() :

    fps = FunctionPools(load_config(CONFIG_JSON))
    rib = RoutingInformationBase(fps)
    
    # Test
    f = Flow("fp1-private", [ "fp1-fn1", "fp1-cgn", "fp2-fn1" ],
             "10.1.5.0/24", "130.128.255.5")

    rib.add_flow(f)
    

if __name__ == '__main__' :
    main()
