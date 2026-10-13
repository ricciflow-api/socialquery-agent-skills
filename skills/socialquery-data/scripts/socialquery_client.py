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
        return self.request("GET", path, parameters, authenticated, idempotency_key)

    def request(self, method, path, parameters=None, authenticated=True, idempotency_key=None, max_credits=None):
        if not isinstance(path, str) or not re.fullmatch(r"/v1/[A-Za-z0-9_/-]+", path) or "//" in path:
            raise SocialQueryError("Unsupported API path. Use an endpoint from the public catalog.")
        if method not in ("GET", "POST", "PATCH", "DELETE"):
            raise SocialQueryError("Unsupported HTTP method.")
        if authenticated and not self.api_key:
            raise SocialQueryError("Set SOCIALQUERY_API_KEY in your environment.")
        query = {}
        for name, value in (parameters or {}).items():
            try:
                encoded = value if isinstance(value, str) else json.dumps(value, allow_nan=False, separators=(",", ":"))
            except (ValueError, TypeError, RecursionError):
                raise SocialQueryError("Parameters must contain finite JSON values.") from None
            if len(encoded) > 16000:
                raise SocialQueryError("Parameter exceeds 16000 characters.")
            query[name] = encoded
        url = ORIGIN + path + ("?" + urllib.parse.urlencode(query) if query and method == "GET" else "")
        headers = {"Accept": "application/json"}
        if authenticated:
            headers["x-api-key"] = self.api_key
        if idempotency_key is not None:
            if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", idempotency_key):
                raise SocialQueryError("Invalid idempotency key.")
            headers["Idempotency-Key"] = idempotency_key
        if max_credits is not None:
            if type(max_credits) is not int or max_credits < 0 or max_credits > 9007199254740991:
                raise SocialQueryError("Invalid credit cap.")
            headers["X-Max-Credits"] = str(max_credits)
        body = None
        if method != "GET":
            headers["Content-Type"] = "application/json"
            body = json.dumps(parameters or {}, allow_nan=False).encode()
        request = urllib.request.Request(url, headers=headers, method=method, data=body)
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
        if max_credits is not None and (type(result.get("credits_used")) is not int or result["credits_used"] < 0 or result["credits_used"] > max_credits):
            raise SocialQueryError("Response credit usage exceeded the approved cap or was invalid.")
        return result

    def endpoints(self):
        result = self.get("/v1/meta/endpoints", authenticated=False)
        endpoints = result.get("data", {}).get("endpoints")
        if not isinstance(endpoints, list):
            raise SocialQueryError("Invalid endpoint catalog.")
        return endpoints

    def call_endpoint(self, endpoint_id, parameters, max_credits, idempotency_key=None, allow_mutation=False):
        endpoint = next((item for item in self.endpoints() if item["id"] == endpoint_id), None)
        if endpoint is None:
            raise SocialQueryError("Unknown endpoint ID. Inspect the public endpoint catalog.")
        if endpoint["method"] not in ("GET", "POST", "PATCH", "DELETE"):
            raise SocialQueryError("Unsupported endpoint method.")
        if endpoint["method"] != "GET" and not allow_mutation:
            raise SocialQueryError("Use --allow-mutation for a user-requested POST, PATCH, or DELETE action; the default is GET only.")
        if endpoint["method"] != "GET" and not idempotency_key:
            raise SocialQueryError("Mutating requests require an idempotency key for safe deliberate retries.")
        if not isinstance(parameters, dict):
            raise SocialQueryError("Parameters must be an object.")
        cost = endpoint.get("creditCost")
        pricing = endpoint.get("creditPricing")
        resolved_pricing = isinstance(pricing, dict) and pricing.get("type") == "resolved_endpoint"
        if resolved_pricing:
            if endpoint.get("path") != "/v1/prism/lookup" or type(pricing.get("maxCredits")) is not int or not 1 <= pricing["maxCredits"] <= 9007199254740991:
                raise SocialQueryError("Invalid resolved pricing metadata.")
            cost = pricing["maxCredits"]
        elif isinstance(pricing, dict) and pricing.get("type") == "boolean_option":
            if endpoint.get("path") != "/v1/tiktok/comment" or pricing.get("parameter") != "deep_scan" or type(pricing.get("defaultCredits")) is not int or pricing["defaultCredits"] != 2 or type(pricing.get("enabledCredits")) is not int or pricing["enabledCredits"] != 6:
                raise SocialQueryError("Invalid comment-lookup pricing metadata.")
            raw = parameters.get("deep_scan")
            if "deep_scan" in parameters and not (type(raw) is bool or type(raw) is str and raw in ("true", "false")):
                raise SocialQueryError("deep_scan must be true or false.")
            cost = 6 if raw is True or raw == "true" else 2
        elif isinstance(pricing, dict) and pricing.get("type") == "news_legs":
            expected={"baseCredits":2,"googleCreditsPerLeg":1,"bingArticlesPerCredit":5,"maxLegs":12}
            if endpoint.get("path")!="/v1/search/news" or any(type(pricing.get(k)) is not int or pricing[k]!=v for k,v in expected.items()):
                raise SocialQueryError("Invalid news pricing metadata.")
            countries_raw,engines_raw=parameters.get("countries","US"),parameters.get("engines","google")
            if not isinstance(countries_raw,str) or not isinstance(engines_raw,str): raise SocialQueryError("Invalid news countries or engines.")
            countries=list(dict.fromkeys(x.strip().upper() for x in countries_raw.split(",")))
            engines=list(dict.fromkeys(x.strip().lower() for x in engines_raw.split(",")))
            if not 1<=len(countries)<=12 or any(not re.fullmatch(r"[A-Z]{2}",x) for x in countries) or not engines or any(x not in ("google","bing") for x in engines): raise SocialQueryError("Invalid news countries or engines.")
            def bounded_integer(raw,minimum,maximum):
                if type(raw) not in (int,str) or isinstance(raw,str) and not re.fullmatch(r"[0-9]+",raw) or not minimum<=int(raw)<=maximum: raise SocialQueryError("Invalid news depth or max_legs.")
                return int(raw)
            depth=bounded_integer(parameters.get("depth",10),10,100)
            legs=min(len(countries),bounded_integer(parameters.get("max_legs",12),1,12))
            if depth%10: raise SocialQueryError("Invalid news depth.")
            cost=2+legs*((1 if "google" in engines else 0)+((min(depth,20)+4)//5 if "bing" in engines else 0))
        elif isinstance(pricing, dict) and pricing.get("type") == "shop_regions":
            if endpoint.get("path") != "/v1/tiktokshop/sales" or type(pricing.get("creditsPerRegion")) is not int or pricing["creditsPerRegion"] != 1 or type(pricing.get("maxRegions")) is not int or pricing["maxRegions"] != 8 or pricing.get("defaultRegion") != "US":
                raise SocialQueryError("Invalid shop market pricing metadata.")
            raw = parameters.get("regions", "US")
            if not isinstance(raw, str):
                raise SocialQueryError("Invalid shop markets.")
            regions = [r.strip().upper() for r in raw.split(",")]
            if not 1 <= len(regions) <= 8 or any(r not in ("US","GB","DE","FR","IT","ES","IE","ID","MY","MX","PH","SG","TH","VN","BR","JP") for r in regions):
                raise SocialQueryError("Invalid shop markets.")
            cost = len(set(regions))
        elif isinstance(pricing, dict) and pricing.get("type") == "board_plus_item":
            if endpoint.get("path") != "/v1/tiktok/videos/popular" or pricing.get("baseCredits") != 25 or pricing.get("creditsPerItem") != 1 or pricing.get("defaultLimit") != 20 or pricing.get("maxLimit") != 20:
                raise SocialQueryError("Invalid video-board pricing metadata.")
            raw = parameters.get("limit", 20)
            if not (type(raw) is int or isinstance(raw, str) and re.fullmatch(r"[0-9]+", raw)) or not 1 <= int(raw) <= 20:
                raise SocialQueryError("Invalid video-board limit.")
            cost = 25 + int(raw)
        elif isinstance(pricing, dict) and pricing.get("type") == "trend_boards":
            if endpoint.get("path") != "/v1/tiktok/hashtags/popular" or pricing.get("creditsPerItem") != 2 or pricing.get("minimumCredits") != 6 or pricing.get("maxItems") != 48:
                raise SocialQueryError("Invalid trend-board pricing metadata.")
            cost = 96 if parameters.get("industry") == "all" else 6
        elif isinstance(pricing, dict) and pricing.get("type") == "post_stats_batch":
            if endpoint.get("path") != "/v1/prism/post-stats" or pricing.get("maxItems") != 100 or pricing.get("defaultCredits") != 1 or pricing.get("platformCredits") != {"instagram": 2, "linkedin": 5}:
                raise SocialQueryError("Invalid post-statistics pricing metadata.")
            urls = parameters.get("urls")
            if isinstance(urls, str):
                try:
                    urls = json.loads(urls)
                except (ValueError, TypeError):
                    raise SocialQueryError("Invalid post URLs.")
            if not isinstance(urls, list) or not 1 <= len(urls) <= 100 or any(not isinstance(url, str) or not url.strip() or len(url) > 2048 for url in urls):
                raise SocialQueryError("Invalid post URLs.")
            cost = 0
            for url in urls:
                try:
                    host = (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
                except ValueError:
                    host = ""
                cost += 2 if host == "instagram.com" else 5 if host == "linkedin.com" else 1
        elif isinstance(pricing, dict) and pricing.get("type") == "profile_batch":
            if endpoint.get("path") != "/v1/prism/profiles" or pricing.get("maxItems") != 50 or pricing.get("defaultCredits") != 1 or pricing.get("platformCredits") != {"linkedin": 5}:
                raise SocialQueryError("Invalid profile pricing metadata.")
            items = parameters.get("items")
            if isinstance(items, str):
                try:
                    items = json.loads(items)
                except (ValueError, TypeError):
                    raise SocialQueryError("Invalid profile items.")
            if not isinstance(items, list) or not 1 <= len(items) <= 50 or any(not isinstance(item, dict) or not isinstance(item.get("platform"), str) or not isinstance(item.get("handle"), str) or not item["handle"].strip() for item in items):
                raise SocialQueryError("Invalid profile items.")
            cost = sum(5 if item["platform"] == "linkedin" else 1 for item in items)
        elif isinstance(pricing, dict) and pricing.get("type") == "per_successful_input":
            if endpoint.get("path") != "/v1/youtube/transcripts" or pricing.get("arrayParameter") != "ids" or pricing.get("creditsPerItem") != 3 or pricing.get("maxItems") != 100:
                raise SocialQueryError("Invalid batch pricing metadata.")
            ids = parameters.get("ids")
            if isinstance(ids, str):
                try:
                    ids = json.loads(ids)
                except (ValueError, TypeError):
                    raise SocialQueryError("Invalid transcript IDs.")
            if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]{11}", item) for item in ids):
                raise SocialQueryError("Invalid transcript IDs.")
            cost = len(ids) * 3
        elif pricing is not None:
            if not isinstance(pricing, dict) or pricing.get("type") != "per_item" or any(type(pricing.get(k)) is not int or pricing[k] < 1 for k in ("creditsPerItem", "defaultLimit", "maxLimit")) or pricing["defaultLimit"] > pricing["maxLimit"] or not isinstance(pricing.get("limitParameter"), str):
                raise SocialQueryError("Invalid metered pricing metadata.")
            raw = parameters.get(pricing["limitParameter"], pricing["defaultLimit"])
            if type(raw) not in (str, int) or not re.fullmatch(r"[0-9]+", str(raw)):
                raise SocialQueryError("Invalid metered request limit.")
            limit = int(raw)
            if limit < 1 or limit > pricing["maxLimit"]:
                raise SocialQueryError("Invalid metered request limit.")
            cost = limit * pricing["creditsPerItem"]
        if type(max_credits) is not int or max_credits < 0 or max_credits > 9007199254740991 or type(cost) is not int or cost < 0 or (not resolved_pricing and cost > max_credits):
            raise SocialQueryError("The maximum request charge exceeds max_credits, or the budget/cost is invalid.")
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
        return self.request(endpoint["method"], path, query, idempotency_key=idempotency_key, max_credits=max_credits)
