#!/usr/bin/env python3


import re
import os
import sys
import json
import time

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


from flask import Flask, make_response, jsonify
app = Flask(__name__)

rib = None # Routing Information Base for flow routes


class logger_wrapper :
    def __init__(self) :
        errmsg = None
        return

    def info(self, msg) :
        logger.info("INFO: %s" % msg)

    def error(self, msg) :
        self.errmsg = msg
        logger.error("ERROR: %s" % msg)

# XXX: should handle with individual logger_wrapper instances for each request
log = logger_wrapper()


CONFIG_JSON = os.path.join(os.path.dirname(__file__), 'config.json')


class Function :

    def __init__(self, name, rdtop, rdbot, marktop, markbot,  cgn) :
        self.name = name
        self.rdtop = rdtop
        self.rdbot = rdbot
        self.marktop = marktop
        self.markbot = markbot
        self.cgn = cgn
        self.fp = None
        return


class FunctionPool :

    def __init__(self, name, community, neighbor) :
        self.name = name
        self.community = community
        self.neighbor = neighbor
        self.functions = {} # key:fn.name, value:class Function
        self.inter_fp_rd = {
            "global" : {}, # key: fp.name, value: rd
            "private" : {},
        }
        self.user_vrf_rd = {} # key: global/private, value:rd
        return

    def __eq__(self, other) :
        return self.name == other.name

    def __ne__(self, other) :
        return not self.__eq__(other)

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


    def add_inter_fp_rd(self, slicename, fpname, rd) :

        if fpname in self.inter_fp_rd[slicename] :
            raise RuntimeError('Duplicated Inter FP RD "%s" in %s',
                               rd, self.name)
        self.inter_fp_rd[slicename][fpname] = rd
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
            
    def find_fp_by_name(self, name) :

        for fp in self.fps :

            # check user-vrf
            for vn in fp.user_vrf_rd :
                if vn == name :
                    return fp

            # check function name
            for fnname in fp.functions :
                if fnname == name :
                    return fp

        return None

    def find_function_by_name(self, fnname) :

        for fp in self.fps :
            if fnname in fp.functions :
                return fp.functions[fnname]
        return None

    def find_inter_fp_rd(self, fp_from, fp_to, is_private) :

        if is_private :
            inter_fp_rd = fp_from.inter_fp_rd["private"]
        else :
            inter_fp_rd = fp_from.inter_fp_rd["global"]
                
        if not fp_to.name in inter_fp_rd :
            return None

        return inter_fp_rd[fp_to.name]


    def generate_tos_flows(self) :

        eroutes = []
        iroutes = []

        flowfmt4 = ("neighbor {neighbor} "
                    + "announce flow route {{ "
                    + "rd {rd}; "
                    + "match {{ destination 0.0.0.0/0; dscp {mark}; }} "
                    + "then {{"
                    + "community [{community}]; "
                    + "extended-community target:{rd}; "
                    + "redirect {redirect}; "
                    + "}} }}")

        flowfmt6 = ("neighbor {neighbor} "
                    + "announce flow route {{ "
                    + "rd {rd}; "
                    + "match {{ destination 0::0/0; dscp {mark}; }} "
                    + "then {{"
                    + "community [{community}]; "
                    + "extended-community target:{rd}; "
                    + "redirect {redirect}; "
                    + "}} }}")


        # Global
        for fp in self.fps :
            for fnname, fn in fp.functions.items() :
                for efp in self.fps :
                    if efp == fp : continue
                    interfp_rd = self.find_inter_fp_rd(efp, fp, False)
                    eroute4 = flowfmt4.format(neighbor = fp.neighbor,
                                              rd = interfp_rd,
                                              mark = fn.markbot,
                                              community = fp.community,
                                              redirect = fn.rdbot)
                    eroute6 = flowfmt6.format(neighbor = fp.neighbor,
                                              rd = interfp_rd,
                                              mark = fn.markbot,
                                              community = fp.community,
                                              redirect = fn.rdbot)
                    eroutes.append(eroute4)
                    eroutes.append(eroute6)

                    iroute4 = flowfmt4.format(neighbor = fp.neighbor,
                                              rd = interfp_rd,
                                              mark = fn.marktop,
                                              community = fp.community,
                                              redirect = fn.rdtop)
                    iroute6 = flowfmt6.format(neighbor = fp.neighbor,
                                              rd = interfp_rd,
                                              mark = fn.marktop,
                                              community = fp.community,
                                              redirect = fn.rdtop)
                    iroutes.append(iroute4)
                    iroutes.append(iroute6)

        # Private
        for fp in self.fps :
            for fnname, fn in fp.functions.items() :
                for efp in self.fps :
                    if efp == fp : continue
                    interfp_rd = self.find_inter_fp_rd(efp, fp, True)
                    eroute4 = flowfmt4.format(neighbor = fp.neighbor,
                                              rd = interfp_rd,
                                              mark = fn.markbot,
                                              community = fp.community,
                                              redirect = fn.rdbot)
                    eroute6 = flowfmt6.format(neighbor = fp.neighbor,
                                              rd = interfp_rd,
                                              mark = fn.markbot,
                                              community = fp.community,
                                              redirect = fn.rdbot)
                    eroutes.append(eroute4)
                    eroutes.append(eroute6)

                    iroute4 = flowfmt4.format(neighbor = fp.neighbor,
                                              rd = interfp_rd,
                                              mark = fn.marktop,
                                              community = fp.community,
                                              redirect = fn.rdtop)
                    iroute6 = flowfmt6.format(neighbor = fp.neighbor,
                                              rd = interfp_rd,
                                              mark = fn.marktop,
                                              community = fp.community,
                                              redirect = fn.rdtop)
                    iroutes.append(iroute4)
                    iroutes.append(iroute6)



        for route in eroutes :
            logger.info("announce inter-fp TOS flow routes for Egress.")
            sys.stdout.write("%s\n" % route)
            sys.stdout.flush()

        for route in iroutes :
            logger.info("announce inter-fp TOS flow routes for Ingress.")
            sys.stdout.write("%s\n" % route)
            sys.stdout.flush()


    
class Flow :

    def __init__(self, start, chain, prefix, prefix_natted) :

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


    def __str__(self) :
        return "<%s(%s):%s>" % (self.prefix, self.prefix_natted,
                                self.chain)


    def show(self, extensive = False, html = False) :

        fmt = ("Prefix {prefix}\n" +
               "    Natted Prefix: {prefix_natted}\n" +
               "    User VRF: {start}\n"
               "    Chain: {chain}\n")

        out = fmt.format(prefix = self.prefix,
                         prefix_natted = self.prefix_natted,
                         start = self.start,
                         chain = " ".join(self.chain))

        if extensive :
            out += "    ExaBGP Egress Routes:\n"
            out += "\n".join(self.eroutes)
            out += "\n"
            out += "    ExaBGP Ingress Routes:\n"
            out += "\n".join(self.iroutes)
            out += "\n"

        if html :
            out = "<pre>" + out
            out = out + "</pre>"

        return out


    def url(self) :

        fmt = ("/add/{prefix}/{preflen}/{prefix_natted}/{preflen_natted}/" +
               "{start}/{chain_string}")

        prefix, preflen = self.prefix.split("/")
        if self.prefix_natted :
            prefix_natted, preflen_natted = self.prefix_natted.split("/")
        else :
            prefix_natted = "none"
            preflen_natted = "none"

        return fmt.format(prefix = prefix, preflen = preflen,
                          prefix_natted = prefix_natted,
                          preflen_natted = preflen_natted,
                          start = self.start,
                          chain_string = "_".join(self.chain))


    def json(self) :

        return {
            "prefix" : self.prefix,
            "prefix_natted" : self.prefix_natted,
            "start" : self.start,
            "chain" : self.chain,
            "exabgp" : {
                "egress_routes" : self.eroutes,
                "ingress_routes" : self.iroutes,
            }
        }


    def is_cgn_included(self, fps) :
        
        # does this chain include CGN?
        for fnname in self.chain :
            fn = fps.find_function_by_name(fnname)
            if not fn :
                log.error("Cannot find Function for '%s'" % fnname)
                return False
            if fn.cgn :
                return True
        return False


    def validate(self, fps) :
        """
        1. check is prefix correct
        2. check existence of user vrf
        3. check existence of functions of the chain
        4. check existence of inter-fp-rd
        5. check loop of functions
        """

        if not validate_prefix(self.prefix) :
            return False
        if self.prefix_natted and not validate_prefix(self.prefix_natted) :
            return False

        if self.prefix_natted :
            before = whichipversion(self.prefix.split("/")[0])
            after = whichipversion(self.prefix_natted.split("/")[0])
            if before != after :
                log.error("Address Family Mismatch between NAT")
                return False

        if not fps.find_rd_of_user_vrf(self.start) :
            log.error("Cannot find user VRF for '%s' for flow %s" %
                         (self.start, self))
            return False

        inter_fp_cgn = True
        cgn_passed = False
        cgn_exists = self.is_cgn_included(fps)

        for x in range(len(self.chain) - 1) :

            prev_fn = fps.find_function_by_name(self.chain[x])
            next_fn = fps.find_function_by_name(self.chain[x + 1])

            if not cgn_exists :
                inter_fp_cgn = False
            else :
                if prev_fn.cgn :
                    inter_fp_cgn = False

            if not prev_fn :
                log.error("Cannot find function '%s' for flow %s" %
                             (self.chain[x], self))
                return False
            if not next_fn :
                log.error("Cannot find function '%s' for flow %s" %
                             (self.chain[x + 1], self))
                return False

            if prev_fn.fp != next_fn.fp :
                if not fps.find_inter_fp_rd(prev_fn.fp, next_fn.fp,
                                            inter_fp_cgn) :
                    log.error("Cannot find inter-fp-rd from %s to %s" %
                                 (prev_fn.fp.name, next_fn.fp.name))
                    return False
                if not fps.find_inter_fp_rd(next_fn.fp, prev_fn.fp,
                                            inter_fp_cgn) :
                    log.error("Cannot find inter-fp-rd from %s to %s" %
                                 (next_fn.fp.name, prev_fn.fp.name))
                    return False

        if len(self.chain) != len(set(self.chain)) :
            log.error("Loop Detected in the flow %s" % self)
            return False

        return True
        

    def encode(self, fps) :
        """ @fps: FunctionPools
        Encode the chain of function names into exabgp flow routes

        An ingress flow is composed from following steps:
        1.
          redirect to the bottom VRF from user vrf (self.start).
        2.
          if the next fuction is in the same FP,
            redirect to bottom VRF of next function from the top of previous.
          if the next function is in the different FP,
            redirect to the inter-fp-rd with set mark of the next function.
        3.
          repeat the step 2 to reach the bottom VRF of the last Function.

        4.
          install flows from all FPs to the top VRF of the last function.

        all flows have the state { match source self.prefix }.
        Note that after cgn == ture Function, use prefix_natted.
        """
        
        flowfmt = ("neighbor {neighbor} "
                   + "UPDATE flow route {{ "
                   + "rd {rd}; "
                   + "match {{ {direct} {prefix}; }} "
                   + "then {{"
                   + "community [{community}]; "
                   + "extended-community target:{rd}; "
                   + "{mark} "
                   + "redirect {redirect};"
                   + "}} }}")

        # does this chain include CGN?
        cgn_exists = self.is_cgn_included(fps)

        # Step 1. bring flows to the first fp
        user_rd = fps.find_rd_of_user_vrf(self.start)
        first_fp = fps.find_fp_by_name(self.chain[0])
        next_fn = fps.find_function_by_name(self.chain[0])

        if not user_rd :
            log.error("Cannot find user VRF for '%s'" % self.start)
            return False
        if not first_fp :
            log.error("Cannot find FP for name '%s'" % self.start)
            return False
        if not next_fn :
            log.error("Cannot find function '%s'" % self.chain[0])
            return False

        for fp in fps.fps :
            if fp == first_fp :
                mark = ""
                redirect = next_fn.rdbot
            else :
                mark = "mark %d;" % next_fn.markbot
                redirect = fps.find_inter_fp_rd(fp, next_fn.fp, cgn_exists)
            
            eroute = flowfmt.format(rd = user_rd,
                                    community =fp.community,
                                    neighbor = fp.neighbor,
                                    direct = "source",
                                    prefix = self.prefix,
                                    mark = mark,
                                    redirect = redirect)
            self.eroutes.append(eroute)


        
        # Step 2.
        cgn_passed = False
        if not cgn_exists :
            inter_fp_cgn = False
        else :
            inter_fp_cgn = True
            

        for x in range(len(self.chain) - 1) :

            prev_fn = fps.find_function_by_name(self.chain[x])
            next_fn = fps.find_function_by_name(self.chain[x + 1])

            # If CGN passed, switch target prefix to prefix_natted
            if prev_fn.cgn :
                cgn_passed = True
                inter_fp_cgn = False
                
            mark_egress = ""
            mark_ingress = ""
            redirect_egress = next_fn.rdbot
            redirect_ingress = prev_fn.rdtop

            # Check is this inter-fp flow ?
            if prev_fn.fp != next_fn.fp :
                # Egress
                inter_fp_rd = fps.find_inter_fp_rd(prev_fn.fp, next_fn.fp,
                                                   inter_fp_cgn)
                mark_egress = "mark %d;" % next_fn.markbot
                redirect_egress = inter_fp_rd

                # Ingress
                inter_fp_rd = fps.find_inter_fp_rd(next_fn.fp, prev_fn.fp,
                                                   inter_fp_cgn)
                mark_ingress = "mark %d;" % prev_fn.marktop
                redirect_ingress = inter_fp_rd

            if cgn_passed and self.prefix_natted :
                prefix = self.prefix_natted
            else :
                prefix = self.prefix

            # Egress Route
            rd = prev_fn.rdtop
            eroute = flowfmt.format(rd = rd,
                                    community = prev_fn.fp.community,
                                    neighbor = prev_fn.fp.neighbor,
                                    direct = "source",
                                    prefix = prefix,
                                    mark = mark_egress,
                                    redirect = redirect_egress)
            # Ingress Route
            rd = next_fn.rdbot
            iroute = flowfmt.format(rd = rd,
                                    community = next_fn.fp.community,
                                    neighbor = next_fn.fp.neighbor,
                                    direct = "destination",
                                    prefix = prefix,
                                    mark = mark_ingress,
                                    redirect = redirect_ingress)

            self.eroutes.append(eroute)
            self.iroutes.append(iroute)


        # Step 4.
        flowfmt = ("neighbor {neighbor} "
                   + "UPDATE flow route {{ "
                   + "match {{ destination {prefix}; }} "
                   + "then {{"
                   + "community [{community}]; "
                   + "{mark} "
                   + "redirect {redirect};"
                   + "}} }}")

        last_fn = fps.find_function_by_name(self.chain[len(self.chain) - 1])
        if last_fn.cgn :
            # if last FN is CGN, Step 2 does not switch cgn_passed.
            cgn_passed = True
            inter_fp_cgn = False

        if cgn_passed and self.prefix_natted :
            prefix = self.prefix_natted
        else :
            prefix = self.prefix

        for fp in fps.fps :
            if last_fn.fp == fp :
                # Fp is the same fp of the last Function
                iroute = flowfmt.format(community = fp.community,
                                        neighbor = fp.neighbor,
                                        prefix = prefix,
                                        mark = "",
                                        redirect = last_fn.rdtop)
            else :
                # For different FP flow route
                inter_fp_rd = fps.find_inter_fp_rd(fp, last_fn.fp,
                                                   inter_fp_cgn)
                mark = "mark %d;" % last_fn.marktop
                iroute = flowfmt.format(community = fp.community,
                                        neighbor = fp.neighbor,
                                        prefix = prefix,
                                        mark = mark,
                                        redirect = inter_fp_rd)
            self.iroutes.append(iroute)

        return True


    def announce(self) :
        for r in self.eroutes :
            sys.stdout.write("%s\n" % r.replace("UPDATE", "announce"))
            sys.stdout.flush()
        for r in self.iroutes :
            sys.stdout.write("%s\n" % r.replace("UPDATE", "announce"))
            sys.stdout.flush()

        return
        

    def withdraw(self) :
        for r in self.eroutes :
            sys.stdout.write("%s\n" % r.replace("UPDATE", "withdraw"))
            sys.stdout.flush()
        for r in self.iroutes :
            sys.stdout.write("%s\n" % r.replace("UPDATE", "withdraw"))
            sys.stdout.flush()

        return

    


class RoutingInformationBase :

    def __init__(self, fps) :

        self.fps = fps
        self.flows = []
        return

    def __iter__(self) :
        return self.flows.__iter__()

    def len(self) :
        return len(self.flows)

    def find_flow(self, f) :
        
        for flow in self.flows :
            if f == flow :
                return flow
        return None

    def find_flow_by_prefix(self, prefix) :

        for f in self.flows :
            if f.prefix == prefix :
                return f
            if f.prefix_natted == prefix :
                return f
        return None

    def add_flow(self, flow) :

        log.info("Add Flow: %s" % flow)

        if not flow.validate(self.fps) :
            log.error("Validation Failed: %s" % flow)
            return False
        
        if (self.find_flow_by_prefix(flow.prefix) or
            (flow.prefix_natted and 
             self.find_flow_by_prefix(flow.prefix_natted))) :
            log.error("Flow for Prefix '%s(%s)' already exists" %
                         (flow.prefix, flow.prefix_natted))
            return False

        ret = flow.encode(self.fps)
        if not ret :
            return False

        self.flows.append(flow)

        flow.announce()

        return True


    def delete_flow(self, flow) :

        log.info("Delete Flow : %s" % flow)

        flow.withdraw()
        self.flows.remove(flow)
        return
        


def load_config(configjson) :

    log.info("Start to load config file %s" % configjson)

    fps = []

    with open(configjson, 'r') as f :
        cfg = json.load(f)

    for fpname, v in cfg.items() :
        log.info("Load Function Pool %s" % fpname)

        fp = FunctionPool(fpname,
                          cfg[fpname]["community"], cfg[fpname]["neighbor"])

        for f in v["function"] :
            log.info("Add Function %s to %s" % (f["name"], fpname))

            fn = Function(f["name"], f["rd-top"], f["rd-bot"],
                          f["mark-top"], f["mark-bottom"],
                          f["cgn"])
            fp.add_function(fn)

        for fpname, rd in v["inter-fp-rd"]["global"].items() :
            fp.add_inter_fp_rd("global", fpname, rd)

        for fpname, rd in v["inter-fp-rd"]["private"].items() :
            fp.add_inter_fp_rd("private", fpname, rd)

            
        for vrfname, rd in v["user-vrf-rd"].items() :
            fp.add_user_vrf_rd(vrfname, rd)
        
        fps.append(fp)

    return fps



""" REST API """

@app.route("/add/<prefix>/<preflen>/<prefix_natted>/<preflen_natted>/" +
           "<start>/<chain_string>",
           methods = ["GET", "POST"])
def rest_add_flow(prefix, preflen, prefix_natted, preflen_natted,
                  start, chain_string) :
    """
    @start : user vrf name
    @prefix: user prefix
    @prefix_natted: user prefix after NAT. if not, use 'none'.
    @chain : <fpname>_<fpname>_<fpname>...
    """
    
    chain = chain_string.split("_")
    prefix += "/" + preflen
    if prefix_natted == "none" :
        prefix_natted = None
    else :
        prefix_natted += "/" + preflen_natted

    response = make_response()

    flow = Flow(start, chain, prefix, prefix_natted)
    if not flow.validate(rib.fps) :
        response.data = log.errmsg
        response.status_code = 400
        return response

    if not rib.add_flow(flow) :
        response.data = log.errmsg
        response.status_code = 400
        return response

    response.data = "Flow : %s is added" % flow
    response.status_code = 200

    return response


@app.route("/override/<prefix>/<preflen>/<prefix_natted>/<preflen_natted>/" +
           "<start>/<chain_string>",
           methods = ["GET", "POST"])
def rest_override_flow(prefix, preflen, prefix_natted, preflen_natted,
                       start, chain_string) :
    """
    @start : user vrf name
    @prefix: user prefix
    @prefix_natted: user prefix after NAT. if not, use 'none'.
    @chain : <fpname>_<fpname>_<fpname>...
    """
    
    chain = chain_string.split("_")
    prefix += "/" + preflen
    if prefix_natted == "none" :
        prefix_natted = None
    else :
        prefix_natted += "/" + preflen_natted


    response = make_response()

    flow = Flow(start, chain, prefix, prefix_natted)


    if not flow.validate(rib.fps) :
        response.data = log.errmsg
        response.status_code = 400
        return response

    if (rib.find_flow_by_prefix(flow.prefix) or
        (flow.prefix_natted and 
         rib.find_flow_by_prefix(flow.prefix_natted))) :
        remove_flow = rib.find_flow_by_prefix(prefix)
        if not remove_flow :
            remove_flow = rib.find_flow_by_prefix(flow.prefix_natted)

        rib.delete_flow(remove_flow)

    if not rib.add_flow(flow) :
        response.data = log.errmsg
        response.status_code = 400
        return response

    response.data = "Flow : %s is overridden" % flow
    response.status_code = 200

    return response



@app.route("/delete/<prefix>/<preflen>", methods = ["GET", "POST"])
def rest_delete_flow(prefix, preflen) :
    """
    @prefix: user prefix for deleting flow
    """

    prefix += "/" + preflen
    response = make_response()

    flow = rib.find_flow_by_prefix(prefix)
    if not flow :
        response.data = "No matched flor for %s" % prefix
        response.status_code = 400
        return response

    rib.delete_flow(flow)
    response.data = "Flow: %s is deleted" % flow
    response.status_code = 200

    return response
    

@app.route("/show/flow", methods = ["GET"])
def rest_show_flow() :

    outputs = []

    for flow in rib :
        outputs.append(flow.show())

    response = make_response()
    response.data = "\n".join(outputs)
    response.status_code = 200

    return response


@app.route("/show/flow/extensive", methods = ["GET"])
def rest_show_flow_extensive() :

    outputs = []

    for flow in rib :
        outputs.append(flow.show(extensive = True))

    response = make_response()
    response.data = "\n".join(outputs)
    response.status_code = 200

    return response

@app.route("/show/flow/html", methods = ["GET"])
def rest_show_flow_html() :

    outputs = ["<html>"]

    if not rib.len() :
        outputs.append("no flow installed.")
    else :
        for flow in rib :
            outputs.append(flow.show(extensive = True, html = True))

    outputs.append("</html>")

    response = make_response()
    response.data = "\n".join(outputs)
    response.status_code = 200

    return response


@app.route("/show/flow/url", methods = ["GET"])
def rest_show_flow_url() :

    outputs = []
    
    for flow in rib :
        outputs.append(flow.url())

    response = make_response()
    response.data = "\n".join(outputs)
    response.status_code = 200

    return response

@app.route("/show/flow/json", methods = ["GET"])
def rest_show_flow_json() :

    flows = []

    for flow in rib :
        flows.append(flow.json())

    response = jsonify(flows)
    response.status_code = 200

    return response


""" Misc """

def whichipversion(addr) :

    if re.match(r'^(\d{1,3}\.){3,3}\d{1,3}$', addr)  :
        return 4

    if re.match(r'((([0-9a-f]{1,4}:){7}([0-9a-f]{1,4}|:))|(([0-9a-f]{1,4}:){6}(:[0-9a-f]{1,4}|((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})|:))|(([0-9a-f]{1,4}:){5}(((:[0-9a-f]{1,4}){1,2})|:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3})|:))|(([0-9a-f]{1,4}:){4}(((:[0-9a-f]{1,4}){1,3})|((:[0-9a-f]{1,4})?:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9a-f]{1,4}:){3}(((:[0-9a-f]{1,4}){1,4})|((:[0-9a-f]{1,4}){0,2}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9a-f]{1,4}:){2}(((:[0-9a-f]{1,4}){1,5})|((:[0-9a-f]{1,4}){0,3}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(([0-9a-f]{1,4}:){1}(((:[0-9a-f]{1,4}){1,6})|((:[0-9a-f]{1,4}){0,4}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:))|(:(((:[0-9a-f]{1,4}){1,7})|((:[0-9a-f]{1,4}){0,5}:((25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}))|:)))(%.+)?\s*$', addr) :
        return 6

    return -1


def validate_prefix(prefix) :

    p, l = prefix.split("/")
    v = whichipversion(p)

    try :
        preflen = int(l)
    except :
        log.error("Invalid Prefix '%s'" % prefix)
        return False

    if v == 4 :
        if preflen < 0 or preflen > 32 :
            log.error("Invalid IPv4 Prefix '%s'" % prefix)

            return False
    elif v == 6 :
        if preflen < 0 or preflen > 128 :
            log.error("Invalid IPv6 Prefix '%s'" % prefix)

            return False
    else :
        log.error("Invalid Prefix '%s'" % prefix)
        return False

    return True



def main() :

    global rib

    fps = FunctionPools(load_config(CONFIG_JSON))
    rib = RoutingInformationBase(fps)

    fps.generate_tos_flows()
    
    app.run(host = "0.0.0.0", debug = True)


if __name__ == '__main__' :
    main()
