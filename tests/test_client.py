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
    def __init__(self): self.requests=[]
    def open(self, request, timeout):
        self.requests.append(request)
        return io.BytesIO(json.dumps({"success":True,"data":{"endpoints":[ENDPOINT]}}).encode())

class ClientTests(unittest.TestCase):
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
