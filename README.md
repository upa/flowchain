

## Chaining Functions using Flowspec


#### ADD or DELETE Flow

method is GET or POST. Note that if not use NAT, use `none` for prefix_natted
and preflen_natted.

- ADD: http://IPADDR/add/<prefix>/<preflen>/<prefix_natted>/<preflen_natted>/<start>/<chain_string>
- DELETE: http://IPADDR/del/<prefix>/<preflen>


#### Show Flows

- http://IPADDR/show/flow
- http://IPADDR/show/flow/extensive
- http://IPADDR/show/flow/url


Example

using [HTTPie](https://httpie.org/).

```shell-session
% http POST http://172.16.0.227:5000/add/10.1.1.0/24/192.168.255.1/32/fp1-private/fp1-fn1_fp1-cgn
HTTP/1.0 200 OK
Content-Length: 70
Content-Type: text/html; charset=utf-8
Date: Fri, 27 Apr 2018 14:45:09 GMT
Server: Werkzeug/0.12.2-dev Python/3.6.3

Flow : <10.1.1.0/24(192.168.255.1/32):['fp1-fn1', 'fp1-cgn']> is added

% http POST http://172.16.0.227:5000/add/10.1.2.0/24/192.168.255.2/32/fp1-private/fp1-fn1_fp1-cgn
HTTP/1.0 200 OK
Content-Length: 70
Content-Type: text/html; charset=utf-8
Date: Fri, 27 Apr 2018 14:45:19 GMT
Server: Werkzeug/0.12.2-dev Python/3.6.3

Flow : <10.1.2.0/24(192.168.255.2/32):['fp1-fn1', 'fp1-cgn']> is added

% http POST http://172.16.0.227:5000/add/192.168.3.0/24/none/none/fp1-private/fp1-fn1_fp2-fn2
HTTP/1.0 200 OK
Content-Length: 55
Content-Type: text/html; charset=utf-8
Date: Fri, 27 Apr 2018 14:45:42 GMT
Server: Werkzeug/0.12.2-dev Python/3.6.3

Flow : <192.168.3.0/24:['fp1-fn1', 'fp2-fn2']> is added

% http GET http://172.16.0.227:5000/show/flow
HTTP/1.0 200 OK
Content-Length: 317
Content-Type: text/html; charset=utf-8
Date: Fri, 27 Apr 2018 14:45:51 GMT
Server: Werkzeug/0.12.2-dev Python/3.6.3

Prefix 10.1.1.0/24
    Natted Prefix: 192.168.255.1/32
    User VRF: fp1-private
    Chain: fp1-fn1 fp1-cgn

Prefix 10.1.2.0/24
    Natted Prefix: 192.168.255.2/32
    User VRF: fp1-private
    Chain: fp1-fn1 fp1-cgn

Prefix 192.168.3.0/24
    Natted Prefix: None
    User VRF: fp1-private
    Chain: fp1-fn1 fp2-fn2

% http GET http://172.16.0.227:5000/show/flow/extensive
HTTP/1.0 200 OK
Content-Length: 2098
Content-Type: text/html; charset=utf-8
Date: Fri, 27 Apr 2018 14:45:55 GMT
Server: Werkzeug/0.12.2-dev Python/3.6.3

Prefix 10.1.1.0/24
    Natted Prefix: 192.168.255.1/32
    User VRF: fp1-private
    Chain: fp1-fn1 fp1-cgn
    ExaBGP Egress Routes:
flow route { rd 290:1500; match { source 10.1.1.0/24; } then {extended-community target:290:1500;  reidrect 290:1201;} }
flow route { rd 290:1101; match { source 10.1.1.0/24; } then {extended-community target:290:1101;  reidrect 290:1204;} }
    ExaBGP Ingress Routes:
flow route { rd 290:1204; match { destination 10.1.1.0/24; } then {extended-community target:290:1204;  reidrect 290:1101;} }
flow route { match { destination 10.1.1.0/24; } then { reidrect 290:1104;} }
flow route { match { destination 10.1.1.0/24; } then {mark : 4; reidrect 290:2001;} }

Prefix 10.1.2.0/24
    Natted Prefix: 192.168.255.2/32
    User VRF: fp1-private
    Chain: fp1-fn1 fp1-cgn
    ExaBGP Egress Routes:
flow route { rd 290:1500; match { source 10.1.2.0/24; } then {extended-community target:290:1500;  reidrect 290:1201;} }
flow route { rd 290:1101; match { source 10.1.2.0/24; } then {extended-community target:290:1101;  reidrect 290:1204;} }
    ExaBGP Ingress Routes:
flow route { rd 290:1204; match { destination 10.1.2.0/24; } then {extended-community target:290:1204;  reidrect 290:1101;} }
flow route { match { destination 10.1.2.0/24; } then { reidrect 290:1104;} }
flow route { match { destination 10.1.2.0/24; } then {mark : 4; reidrect 290:2001;} }

Prefix 192.168.3.0/24
    Natted Prefix: None
    User VRF: fp1-private
    Chain: fp1-fn1 fp2-fn2
    ExaBGP Egress Routes:
flow route { rd 290:1500; match { source 192.168.3.0/24; } then {extended-community target:290:1500;  reidrect 290:1201;} }
flow route { rd 290:1101; match { source 192.168.3.0/24; } then {extended-community target:290:1101; mark 2; reidrect 290:1002;} }
    ExaBGP Ingress Routes:
flow route { rd 290:2202; match { destination 192.168.3.0/24; } then {extended-community target:290:2202; mark 1; reidrect 290:2001;} }
flow route { match { destination 192.168.3.0/24; } then {mark : 2; reidrect 290:1002;} }
flow route { match { destination 192.168.3.0/24; } then { reidrect 290:2102;} }

% http GET http://172.16.0.227:5000/show/flow/url
HTTP/1.0 200 OK
Content-Length: 181
Content-Type: text/html; charset=utf-8
Date: Fri, 27 Apr 2018 14:45:59 GMT
Server: Werkzeug/0.12.2-dev Python/3.6.3

/add/10.1.1.0/24/192.168.255.1/32/fp1-private/fp1-fn1_fp1-cgn
/add/10.1.2.0/24/192.168.255.2/32/fp1-private/fp1-fn1_fp1-cgn
/add/192.168.3.0/24/none/none/fp1-private/fp1-fn1_fp2-fn2

%    
```
