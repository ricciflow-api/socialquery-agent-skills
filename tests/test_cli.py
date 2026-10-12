import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

scripts = Path(__file__).resolve().parents[1] / 'skills/socialquery-data/scripts'
sys.path.insert(0, str(scripts))
spec = importlib.util.spec_from_file_location('credit_cli', scripts / 'socialquery_api.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

class CreditCliTests(unittest.TestCase):
    def test_receipts_keep_exact_filter_and_use_zero_cap(self):
        with patch.object(cli, 'SocialQueryClient') as constructor, patch.object(sys, 'argv', ['socialquery_api.py', 'transactions', '--limit', '2', '--cursor', 'opaque', '--request-id', 'req_one']), contextlib.redirect_stdout(io.StringIO()):
            constructor.return_value.request.return_value = {'success': True, 'credits_used': 0}
            self.assertEqual(cli.main(), 0)
            constructor.return_value.request.assert_called_once_with('GET', '/v1/credits/transactions', {'limit': 2, 'cursor': 'opaque', 'request_id': 'req_one'}, max_credits=0)

    def test_invalid_page_size_makes_no_request(self):
        with patch.object(cli, 'SocialQueryClient') as constructor, patch.object(sys, 'argv', ['socialquery_api.py', 'transactions', '--limit', '101']), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(), 1)
            constructor.return_value.request.assert_not_called()
