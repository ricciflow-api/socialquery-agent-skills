"""Standard-library SocialQuery client. No retries or automatic pagination."""
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request

ORIGIN = "https://socialquery.dev"
MAX_BYTES = 4 * 1024 * 1024


class SocialQueryError(Exception):
    pass


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SocialQueryClient:
    def __init__(self, api_key=None, opener=None):
        self.api_key = os.environ.get("SOCIALQUERY_API_KEY") if api_key is None else api_key
        self.opener = opener or urllib.request.build_opener(NoRedirects())

    def get(self, path, parameters=None, authenticated=True, idempotency_key=None):
        if not isinstance(path, str) or not re.fullmatch(r"/v1/[A-Za-z0-9_/-]+", path) or "//" in path:
            raise SocialQueryError("Unsupported API path. Use an endpoint from the public catalog.")
        if authenticated and not self.api_key:
            raise SocialQueryError("Set SOCIALQUERY_API_KEY in your environment.")
        query = {}
        for name, value in (parameters or {}).items():
            if not isinstance(value, (str, int, float, bool)) or (isinstance(value, float) and not math.isfinite(value)):
                raise SocialQueryError("Parameters must be strings, finite numbers, or booleans.")
            encoded = str(value).lower() if isinstance(value, bool) else str(value)
            if len(encoded) > 16000:
                raise SocialQueryError("Parameter exceeds 16000 characters.")
            query[name] = encoded
        url = ORIGIN + path + ("?" + urllib.parse.urlencode(query) if query else "")
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["x-api-key"] = self.api_key
        if idempotency_key is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", idempotency_key):
                raise SocialQueryError("Invalid idempotency key.")
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with self.opener.open(request, timeout=60) as response:
                raw = response.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as error:
            request_id = re.sub(r"[^A-Za-z0-9_-]", "", error.headers.get("x-request-id", "unavailable"))[:100]
            error.close()
            raise SocialQueryError(f"SocialQuery HTTP {error.code}; request ID: {request_id}. No automatic retry was made.") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SocialQueryError("SocialQuery request failed or timed out. No automatic retry was made.") from None
        if len(raw) > MAX_BYTES:
            raise SocialQueryError("API response exceeds 4 MiB. Narrow the query or page size.")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError):
            raise SocialQueryError("API returned invalid JSON.") from None
        if not isinstance(result, dict) or result.get("success") is not True:
            raise SocialQueryError("SocialQuery returned an unsuccessful response.")
        return result

    def endpoints(self):
        result = self.get("/v1/meta/endpoints", authenticated=False)
        endpoints = result.get("data", {}).get("endpoints")
        if not isinstance(endpoints, list):
            raise SocialQueryError("Invalid endpoint catalog.")
        return endpoints

    def call_endpoint(self, endpoint_id, parameters, max_credits, idempotency_key=None):
        endpoint = next((item for item in self.endpoints() if item["id"] == endpoint_id), None)
        if endpoint is None:
            raise SocialQueryError("Unknown endpoint ID. Inspect the public endpoint catalog.")
        if endpoint["method"] != "GET":
            raise SocialQueryError("This helper supports GET only. Use REST for other methods.")
        cost = endpoint.get("creditCost")
        if type(max_credits) is not int or max_credits < 0 or type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0 or cost > max_credits:
            raise SocialQueryError("The catalog credit cost exceeds max_credits, or the budget/cost is invalid.")
        if not isinstance(parameters, dict):
            raise SocialQueryError("Parameters must be an object.")
        specs = endpoint.get("params", [])
        allowed = {param["name"] for param in specs}
        if set(parameters) - allowed:
            raise SocialQueryError("Unknown parameter. Inspect the endpoint catalog.")
        def has_value(name):
            return name in parameters and parameters[name] is not None and parameters[name] != ""
        missing = [param["name"] for param in specs if param.get("required") and not has_value(param["name"])]
        if missing:
            raise SocialQueryError("Missing required parameters: " + ", ".join(missing))
        if any(not any(has_value(name) for name in group) for group in endpoint.get("oneOfParameters", [])):
            raise SocialQueryError("Supply at least one parameter from each alternative group.")
        query = dict(parameters)
        def path_value(match):
            name = match.group(1)
            if not has_value(name) or not re.fullmatch(r"[A-Za-z0-9_-]+", str(parameters[name])):
                raise SocialQueryError("Invalid path parameter.")
            return str(query.pop(name))
        path = re.sub(r"\{([^}]+)\}", path_value, endpoint["path"])
        return self.get(path, query, idempotency_key=idempotency_key)
