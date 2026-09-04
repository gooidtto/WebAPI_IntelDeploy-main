#!/usr/bin/env python3
"""Best-effort Railway control-plane bootstrap; runtime variables stay authoritative."""
import os
import sys
import time
import json
import urllib.error
import urllib.request

# Non-destructive networking policy: never delete existing Railway domains or proxies.
# Do not destructively delete networking resources; only inspect, reuse, or create when absent.

API_URL = "https://backboard.railway.com/graphql/v2"
TARGET_PORT = 8080
RETRIES = max(1, int(os.environ.get("RAILWAY_API_RETRIES", "3")))
DELAY = max(1.0, float(os.environ.get("RAILWAY_API_RETRY_DELAY", "2.5")))
RAILWAY_TOKEN = os.environ.get("RAILWAY_TOKEN", "").strip()
ACCOUNT_TOKEN = os.environ.get("RAILWAY_API_TOKEN", "").strip()
PROJECT_ID = os.environ.get("RAILWAY_PROJECT_ID", "").strip()
ENVIRONMENT_ID = os.environ.get("RAILWAY_ENVIRONMENT_ID", "").strip()
SERVICE_ID = os.environ.get("RAILWAY_SERVICE_ID", "").strip()

class ApiError(RuntimeError):
    def __init__(self, message, retryable=False, auth=False):
        super().__init__(message)
        self.retryable = retryable
        self.auth = auth


def runtime_endpoints_complete():
    public = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
    host = os.environ.get("RAILWAY_TCP_PROXY_DOMAIN", "").strip()
    port = os.environ.get("RAILWAY_TCP_PROXY_PORT", "").strip()
    if not public or not host or not port:
        return False
    if not public.endswith(".up.railway.app") or not host.endswith(".proxy.rlwy.net"):
        return False
    try:
        return 1 <= int(port) <= 65535
    except ValueError:
        return False


def request_once(query, variables, mode, token):
    headers = {"Content-Type": "application/json", "User-Agent": "railway-universal-stable/5.8"}
    if mode == "project":
        headers["Project-Access-Token"] = token
    else:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:700]
        raise ApiError(f"HTTP {exc.code}: {detail}", retryable=exc.code == 429 or 500 <= exc.code <= 599, auth=exc.code in (401,403))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ApiError(f"request failed: {exc}", retryable=True)
    if body.get("errors"):
        detail = json.dumps(body["errors"], ensure_ascii=False)[:1200]
        auth = any("not authorized" in str(e).lower() or "unauthorized" in str(e).lower() for e in body["errors"])
        raise ApiError(detail, retryable=False, auth=auth)
    return body.get("data") or {}


def request(query, variables, mode, token):
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            return request_once(query, variables, mode, token)
        except ApiError as exc:
            last = exc
            if not exc.retryable or attempt >= RETRIES:
                raise
            print(f"RAILWAY_API_RETRY={attempt}/{RETRIES} delay={DELAY:g}s reason=transient")
            time.sleep(DELAY)
    raise last or ApiError("request failed")


def gql(query, variables=None):
    errors = []

    # Compatibility path: RAILWAY_TOKEN may be the account/workspace-style token
    # historically used by this project. Railway authenticates those with Bearer.
    # If it is instead a true project token, the Project-Access-Token fallback below
    # remains available. This keeps both token forms compatible without weakening scope.
    if RAILWAY_TOKEN:
        try:
            data = request(query, variables, "bearer", RAILWAY_TOKEN)
            print("RAILWAY_API_AUTH=RAILWAY_TOKEN_BEARER")
            return data
        except ApiError as exc:
            errors.append(exc)
            if exc.auth:
                print("RAILWAY_API_RAILWAY_TOKEN_BEARER=REJECTED", file=sys.stderr)

        try:
            data = request(query, variables, "project", RAILWAY_TOKEN)
            print("RAILWAY_API_AUTH=RAILWAY_TOKEN_PROJECT")
            return data
        except ApiError as exc:
            errors.append(exc)
            if exc.auth:
                print("RAILWAY_API_RAILWAY_TOKEN_PROJECT=REJECTED", file=sys.stderr)

    if ACCOUNT_TOKEN and ACCOUNT_TOKEN != RAILWAY_TOKEN:
        try:
            data = request(query, variables, "bearer", ACCOUNT_TOKEN)
            print("RAILWAY_API_AUTH=BEARER_FALLBACK")
            return data
        except ApiError as exc:
            errors.append(exc)

    raise errors[-1] if errors else ApiError("no Railway token")


def resolve_ids():
    global PROJECT_ID, ENVIRONMENT_ID, SERVICE_ID

    # Railway injects these IDs into the running service. Prefer them so a
    # workspace/account-style RAILWAY_TOKEN never needs the projectToken query.
    if not PROJECT_ID or not ENVIRONMENT_ID:
        try:
            data = gql("query { projectToken { projectId environmentId } }")
            info = data.get("projectToken") or {}
            PROJECT_ID = PROJECT_ID or str(info.get("projectId", ""))
            ENVIRONMENT_ID = ENVIRONMENT_ID or str(info.get("environmentId", ""))
        except ApiError as exc:
            if not PROJECT_ID or not ENVIRONMENT_ID:
                raise ApiError(f"unable to resolve Railway project/environment ID: {exc}")

    if not PROJECT_ID or not ENVIRONMENT_ID:
        raise ApiError("unable to resolve Railway project/environment ID")

    if not SERVICE_ID:
        data = gql("query($id:String!){ project(id:$id){ services{edges{node{id name}}} } }", {"id": PROJECT_ID})
        services = (((data.get("project") or {}).get("services") or {}).get("edges") or [])
        wanted = os.environ.get("RAILWAY_SERVICE_NAME", "").strip()
        matches = [e.get("node", {}) for e in services if e.get("node", {}).get("name") == wanted]
        if len(matches) == 1:
            SERVICE_ID = str(matches[0].get("id", ""))
        elif len(services) == 1:
            SERVICE_ID = str(services[0].get("node", {}).get("id", ""))
        else:
            raise ApiError("unable to identify target Railway service")
    if not SERVICE_ID:
        raise ApiError("target Railway service ID is empty")


def list_service_domains():
    data = gql("query($id:String!){ environment(id:$id){ config(decryptVariables:false) } }", {"id": ENVIRONMENT_ID})
    config = ((data.get("environment") or {}).get("config")) or {}
    if isinstance(config, str):
        config = json.loads(config)
    svc = ((config.get("services") or {}).get(SERVICE_ID)) or {}
    domains = (svc.get("networking") or {}).get("serviceDomains") or {}
    count = len(domains) if isinstance(domains, (dict, list)) else 0
    print(f"RAILWAY_API_PUBLIC_DOMAIN_CONFIG_COUNT={count}")
    return domains


def create_service_domain():
    print("RAILWAY_API_ACTION=CREATE_PUBLIC_DOMAIN")
    data = gql("mutation($input:ServiceDomainCreateInput!){ serviceDomainCreate(input:$input){domain} }", {"input": {"serviceId": SERVICE_ID, "environmentId": ENVIRONMENT_ID}})
    domain = (data.get("serviceDomainCreate") or {}).get("domain", "")
    if not domain:
        raise ApiError("serviceDomainCreate returned empty domain")
    print(f"RAILWAY_API_PUBLIC_DOMAIN=CREATED domain={domain}")


def ensure_tcp_proxy():
    data = gql(
        "query($serviceId:String!,$environmentId:String!){ tcpProxies(serviceId:$serviceId,environmentId:$environmentId){id domain proxyPort applicationPort} }",
        {"serviceId": SERVICE_ID, "environmentId": ENVIRONMENT_ID},
    )
    proxies = data.get("tcpProxies") or []
    target = []
    for p in proxies:
        try:
            app = int(p.get("applicationPort", -1)); port = int(p.get("proxyPort", -1))
        except (TypeError, ValueError):
            continue
        if app == TARGET_PORT:
            target.append((str(p.get("domain", "")).strip(), port))
    print(f"RAILWAY_API_TCP_PROXY_CONFIG_COUNT={len(proxies)}")
    if len(target) > 1:
        print(f"RAILWAY_API_TCP_PROXY=DUPLICATES count={len(target)} action=NONE")
        return False
    if len(target) == 1:
        print(f"RAILWAY_API_TCP_PROXY=EXISTS target=8080 domain={target[0][0]} port={target[0][1]}")
        return False
    print("RAILWAY_API_ACTION=CREATE_TCP_PROXY target=8080")
    data = gql(
        "mutation($input:TCPProxyCreateInput!){ tcpProxyCreate(input:$input){id domain proxyPort applicationPort} }",
        {"input": {"serviceId": SERVICE_ID, "environmentId": ENVIRONMENT_ID, "applicationPort": TARGET_PORT}},
    )
    p = data.get("tcpProxyCreate") or {}
    if not p.get("domain") or not p.get("proxyPort"):
        raise ApiError("tcpProxyCreate returned incomplete proxy information")
    print(f"RAILWAY_API_TCP_PROXY=CREATED domain={p['domain']} port={p['proxyPort']} target=8080")
    return True


def setup():
    if not RAILWAY_TOKEN and not ACCOUNT_TOKEN:
        print("RAILWAY_API_SETUP=SKIP reason=no_token")
        return 0
    resolve_ids()
    print("RAILWAY_API_SETUP=CHECK")
    domains = list_service_domains()
    changed = False
    if not domains:
        create_service_domain()
        changed = True
    else:
        print("RAILWAY_API_PUBLIC_DOMAIN=EXISTS_OR_CONFIGURED")
    if ensure_tcp_proxy():
        changed = True
    if changed:
        print("RAILWAY_API_ACTION=REDEPLOY")
        gql("mutation($serviceId:String!,$environmentId:String!){ serviceInstanceRedeploy(serviceId:$serviceId,environmentId:$environmentId) }", {"serviceId": SERVICE_ID, "environmentId": ENVIRONMENT_ID})
        print("RAILWAY_API_SETUP=REDEPLOY_REQUESTED")
        return 10
    print("RAILWAY_API_SETUP=READY")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(setup())
    except Exception as exc:
        if runtime_endpoints_complete():
            print(f"RAILWAY_API_SETUP=DEGRADED reason={exc}", file=sys.stderr)
            print("RAILWAY_API_SETUP=CONTINUE_RUNTIME_ENDPOINTS", file=sys.stderr)
            sys.exit(0)
        print(f"RAILWAY_API_SETUP=ERROR {exc}", file=sys.stderr)
        sys.exit(20)
