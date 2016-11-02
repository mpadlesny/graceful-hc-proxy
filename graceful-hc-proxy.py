from datetime import datetime, timedelta
import json
import os
import pickle
import requests
import sys
import urlparse

try:
    UPSTREAM_ADDRESS = os.environ["UPSTREAM_ADDRESS"]
    START_TIME = pickle.loads(os.environ["START_TIME"])
except KeyError as e:
    sys.stderr.write("ERROR: " + str(e) + " environment variable not defined!\n")
    raise

def parse_gunicorn_headers(environ):
    prefix = "HTTP_"
    ignore = ["host"]
    res = {}
    for k in environ:
        if k.startswith(prefix):
            # underscores are valid in http headers but quite often rejected e.g. by nginx
            # http://nginx.org/en/docs/http/ngx_http_core_module.html#underscores_in_headers
            # or django
            # https://www.djangoproject.com/weblog/2015/jan/13/security/
            header_name = k[len(prefix):].replace("_", "-")
            header_val = environ[k]
            if header_name.lower() in ignore:
                continue
            res[header_name] = header_val
    return res

def merge_upstream_url(upstream_addr, path, query):
    # https://docs.python.org/2/library/urlparse.html#urlparse.urlsplit
    SCHEME   = 0
    NETLOC   = 1
    PATH     = 2
    QUERY    = 3
    FRAGMENT = 4
    r = list(urlparse.urlsplit(upstream_addr))
    r[PATH] = path
    r[QUERY] = query
    return urlparse.urlunsplit(r)

def fetch(method):
    dispatch = { "get": requests.get }
    try:
        return dispatch[method.lower()]
    except KeyError:
        return lambda *args, **kwargs: MockResponse(405)

def get_code_description(code_no):
    try:
        return requests.status_codes._codes[code_no][0]
    except KeyError:
        custom_codes = {
            520: "Unknown Error"
        }
        return custom_codes.get(code_no, "unknown")

def fetch_upstream_gracefully(environ):
    try:
        res = fetch(environ['REQUEST_METHOD'])(
                    merge_upstream_url(UPSTREAM_ADDRESS, environ['PATH_INFO'], environ['QUERY_STRING']),
                    headers=parse_gunicorn_headers(environ),
                    timeout=GracePeriod.timeout())
    except requests.RequestException as e:
        sys.stderr.write(str(e) + "\n")
        res = MockResponse().report(str(e))

    if res.status_code != 200 and not GracePeriod.expired():
        print str(datetime.now()) + " Received " + str(res.status_code) + " but grace period is in effect!"
        return MockResponse(200).report("Upstream returned non 200 status.", res)

    return res

class GracePeriod(object):
    REQUEST_TIMEOUT_DURING_GRACE_PERIOD = float(os.getenv("REQUEST_TIMEOUT_DURING_GRACE_PERIOD", 1))
    GRACE_PERIOD = int(os.getenv("GRACE_PERIOD", 300))

    @staticmethod
    def expired():
        return (datetime.now() - START_TIME) > timedelta(seconds=GracePeriod.GRACE_PERIOD)

    @staticmethod
    def timeout():
        timeout = {
            True: None,
            False: GracePeriod.REQUEST_TIMEOUT_DURING_GRACE_PERIOD
        }
        return timeout[GracePeriod.expired()]

class MockResponse(object):
    def __init__(self, status_code = 520, content = '', headers = None):
        # https://en.wikipedia.org/wiki/List_of_HTTP_status_codes#Cloudflare
        self.status_code = status_code
        self.content = content
        self.headers = {} if headers == None else headers

    def report(self, cause, up_res = None):
        r = {
            "failure": True,
            "cause": cause
        }
        if up_res:
            r["upstream_response"] = {
                "status": up_res.status_code,
                "headers": up_res.headers,
                "body": up_res.content
            }
        self.content = json.dumps(r, indent=4, sort_keys=True)
        return self

def app(environ, start_response):
    res = fetch_upstream_gracefully(environ)

    status = '{} {}'.format(res.status_code, get_code_description(res.status_code))
    response_body = res.content
    response_headers = res.headers.items()

    start_response(status, response_headers)
    return iter([response_body])

