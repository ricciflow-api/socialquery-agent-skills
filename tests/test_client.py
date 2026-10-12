import importlib.util
import io
import json
from pathlib import Path
import unittest
import urllib.error

source = Path(__file__).resolve().parents[1] / "skills/socialquery-data/scripts/socialquery_client.py"
spec = importlib.util.spec_from_file_location("client", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
ENDPOINT = {"id":"get_test", "method":"GET", "path":"/v1/test/search", "creditCost":1, "params":[{"name":"query", "required":True}]}

class Opener:
    def __init__(self, endpoint=ENDPOINT): self.requests=[]; self.endpoint=endpoint
    def open(self, request, timeout):
        self.requests.append(request)
        return io.BytesIO(json.dumps({"success":True,"credits_used":0,"data":{"endpoints":[self.endpoint]}}).encode())

class ClientTests(unittest.TestCase):
    def test_trend_board_fanout_budget(self):
        item={**ENDPOINT,"path":"/v1/tiktok/hashtags/popular","creditCost":6,"params":[{"name":"industry"}],"creditPricing":{"type":"trend_boards","creditsPerItem":2,"minimumCredits":6,"maxItems":48}}
        opener=Opener(item);client=module.SocialQueryClient(api_key="test",opener=opener)
        with self.assertRaises(module.SocialQueryError): client.call_endpoint(item["id"],{"industry":"all"},95)
        self.assertEqual(len(opener.requests),1)
        client.call_endpoint(item["id"],{"industry":"all"},96)
        self.assertEqual(opener.requests[-1].get_header("X-max-credits"),"96")
        client.call_endpoint(item["id"],{},6)
        self.assertEqual(opener.requests[-1].get_header("X-max-credits"),"6")

    def test_post_stat_batch_url_tiers(self):
        item={**ENDPOINT,"method":"POST","path":"/v1/prism/post-stats","params":[{"name":"urls","required":True}],"creditPricing":{"type":"post_stats_batch","maxItems":100,"defaultCredits":1,"platformCredits":{"instagram":2,"linkedin":5}}}
        opener=Opener(item);client=module.SocialQueryClient(api_key="test",opener=opener)
        params={"urls":["https://www.instagram.com/example/p/abc/","https://linkedin.com/posts/example","https://youtu.be/jNQXAC9IVRw","invalid"]}
        with self.assertRaises(module.SocialQueryError): client.call_endpoint(item["id"],params,8,"underfunded",True)
        self.assertEqual(len(opener.requests),1)
        client.call_endpoint(item["id"],params,9,"stats-batch",True)
        self.assertEqual(json.loads(opener.requests[-1].data),params)
        self.assertEqual(opener.requests[-1].get_header("X-max-credits"),"9")

    def test_profile_batch_tiers_and_nested_items(self):
        item={**ENDPOINT,"method":"POST","path":"/v1/prism/profiles","params":[{"name":"items","required":True}],"creditPricing":{"type":"profile_batch","maxItems":50,"defaultCredits":1,"platformCredits":{"linkedin":5}}}
        opener=Opener(item);client=module.SocialQueryClient(api_key="test",opener=opener)
        params={"items":[{"platform":"bluesky","handle":"bsky.app","custom_id":"first"},{"platform":"linkedin","handle":"example"}]}
        with self.assertRaises(module.SocialQueryError): client.call_endpoint(item["id"],params,5,"underfunded",True)
        self.assertEqual(len(opener.requests),1)
        client.call_endpoint(item["id"],params,6,"profile-batch",True)
        self.assertEqual(json.loads(opener.requests[-1].data),params)
        self.assertEqual(opener.requests[-1].get_header("X-max-credits"),"6")

    def test_batch_transcript_budget_counts_ids(self):
        item={**ENDPOINT,"method":"POST","path":"/v1/youtube/transcripts","params":[{"name":"ids","required":True}],"creditPricing":{"type":"per_successful_input","arrayParameter":"ids","creditsPerItem":3,"maxItems":100}}
        opener=Opener(item);client=module.SocialQueryClient(api_key="test",opener=opener)
        params={"ids":["bjVIDXPP7Uk","00000000000"]}
        with self.assertRaises(module.SocialQueryError): client.call_endpoint(item["id"],params,5,"batch-underfunded",True)
        self.assertEqual(len(opener.requests),1)
        client.call_endpoint(item["id"],params,6,"batch-ok",True)
        self.assertEqual(opener.requests[-1].get_header("X-max-credits"),"6")
        self.assertEqual(json.loads(opener.requests[-1].data),params)
    def test_mutations_preserve_method_and_body_with_explicit_intent(self):
        for method in ("POST", "PATCH", "DELETE"):
            item={"id":"change_job","method":method,"path":"/v1/web/jobs/{job_id}","creditCost":0,"params":[{"name":"job_id","required":True},{"name":"urls"},{"name":"options"}]}
            opener=Opener(item)
            client=module.SocialQueryClient(api_key="test",opener=opener)
            params={"job_id":"job_123","urls":["https://example.com"],"options":{"fresh":True,"limit":2}}
            with self.assertRaisesRegex(module.SocialQueryError,"allow-mutation"):
                client.call_endpoint(item["id"],params,0)
            with self.assertRaisesRegex(module.SocialQueryError,"idempotency"):
                client.call_endpoint(item["id"],params,0,allow_mutation=True)
            self.assertEqual(len(opener.requests),2)
            client.call_endpoint(item["id"],params,0,"job-action-123",True)
            request=opener.requests[-1]
            self.assertEqual(request.method,method)
            self.assertEqual(request.full_url,"https://socialquery.dev/v1/web/jobs/job_123")
            self.assertEqual(json.loads(request.data),{"urls":["https://example.com"],"options":{"fresh":True,"limit":2}})
    def test_metered_budget_and_server_cap(self):
        item={**ENDPOINT,"params":[*ENDPOINT["params"],{"name":"limit"}],"creditPricing":{"type":"per_item","creditsPerItem":2,"limitParameter":"limit","defaultLimit":25,"maxLimit":100}}
        opener=Opener(item);client=module.SocialQueryClient(api_key="test",opener=opener)
        with self.assertRaises(module.SocialQueryError): client.call_endpoint(item["id"],{"query":"x","limit":10},19)
        self.assertEqual(len(opener.requests),1)
        client.call_endpoint(item["id"],{"query":"x","limit":"10"},20)
        self.assertEqual(opener.requests[-1].get_header("X-max-credits"),"20")
        for limit in (None,True,0,101,"2.5"):
            with self.assertRaises(module.SocialQueryError): client.call_endpoint(item["id"],{"query":"x","limit":limit},200)
    def test_resolved_prices_preserve_server_cap(self):
        item={**ENDPOINT,"path":"/v1/prism/lookup","params":[{"name":"url","required":True}],"creditPricing":{"type":"resolved_endpoint","maxCredits":5}}
        opener=Opener(item); client=module.SocialQueryClient(api_key="test",opener=opener)
        client.call_endpoint(item["id"],{"url":"https://github.com/octocat/Hello-World"},1)
        self.assertEqual(opener.requests[-1].get_header("X-max-credits"),"1")
        for cap in (None,True,-1,1.5):
            with self.assertRaises(module.SocialQueryError): client.call_endpoint(item["id"],{"url":"https://example.com"},cap)
        bad=Opener({**item,"path":"/v1/test/search"})
        with self.assertRaisesRegex(module.SocialQueryError,"Invalid resolved"):
            module.SocialQueryClient(api_key="test",opener=bad).call_endpoint(item["id"],{"url":"https://example.com"},5)
        self.assertEqual(len(bad.requests),1)
    def test_invalid_usage_is_not_success(self):
        class InvalidUsage:
            def open(self,*args,**kwargs): return io.BytesIO(json.dumps({"success":True,"credits_used":3,"data":{}}).encode())
        with self.assertRaisesRegex(module.SocialQueryError,"credit usage"):
            module.SocialQueryClient(api_key="test",opener=InvalidUsage()).request("GET","/v1/test",{},max_credits=2)
    def test_nested_invalid_number(self):
        opener=Opener()
        with self.assertRaisesRegex(module.SocialQueryError,"finite JSON"):
            module.SocialQueryClient(api_key="test",opener=opener).get("/v1/test",{"options":{"value":float("inf")}})
        self.assertEqual(opener.requests,[])
    def test_request_encoding_and_credentials(self):
        opener=Opener()
        client=module.SocialQueryClient(api_key="test-only",opener=opener)
        client.call_endpoint("get_test",{"query":"a & b"},1)
        self.assertEqual(len(opener.requests),2)
        self.assertIsNone(opener.requests[0].get_header("X-api-key"))
        self.assertEqual(opener.requests[1].get_header("X-api-key"),"test-only")
        self.assertIn("query=a+%26+b",opener.requests[1].full_url)
        self.assertNotIn("test-only",opener.requests[1].full_url)
    def test_invalid_requests_do_not_spend(self):
        for params,budget in [({},1),({"query":"x"},0),({"query":"x","unknown":"y"},1),([],1)]:
            opener=Opener()
            with self.assertRaises(module.SocialQueryError):
                module.SocialQueryClient(api_key="test",opener=opener).call_endpoint("get_test",params,budget)
            self.assertEqual(len(opener.requests),1)
    def test_origins_and_missing_key(self):
        opener=Opener()
        client=module.SocialQueryClient(api_key="",opener=opener)
        for path in ["https://evil.example", "//evil.example", "/v1/../admin", "/v1/%2e%2e/admin", "/api/admin", "/v1/github/profile"]:
            with self.assertRaises(module.SocialQueryError): client.get(path)
        self.assertEqual(opener.requests,[])
    def test_redirect_handler_refuses_following(self):
        self.assertIsNone(module.NoRedirects().redirect_request(None,None,302,"redirect",{},"https://evil.example"))
    def test_http_error_is_bounded_without_private_body(self):
        class Failure:
            count=0
            def open(self,*args,**kwargs):
                self.count+=1
                raise urllib.error.HTTPError("https://socialquery.dev",401,"bad",{"x-request-id":"req_123"},io.BytesIO(b"secret payload"))
        opener=Failure()
        with self.assertRaisesRegex(module.SocialQueryError,"HTTP 401; request ID: req_123") as error:
            module.SocialQueryClient(api_key="test",opener=opener).get("/v1/github/profile")
        self.assertNotIn("secret",str(error.exception))
        self.assertEqual(opener.count,1)

if __name__ == "__main__": unittest.main()
