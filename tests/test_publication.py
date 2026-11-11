import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publication import verify_fresh, stage_site
from pipeline import DataError
from dataset_storage import publish_bundle
from gyeonggi_public import PublicClient


class PublicationTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'config').mkdir()
        (root / 'config/supabase.js').write_text('window.KAPT_SUPABASE_CONFIG={};')
        (root / 'config/not-public.txt').write_text('excluded')
        (root / 'assets').mkdir()
        (root / 'assets/app.js').write_text('// app')
        (root / 'index.html').write_text('<script>window.__EMBEDDED_DATA__={};</script>')
        data = {'meta': {'current_month': '2026-10', 'min_month': '2026-09',
                        'loaded_regions': ['영등포구'], 'complex_count': 1},
                'complexes': [{'id': 'A1', 'name': '단지', 'region': '영등포구',
                               'households': 300, 'tx': [['2026-10-10', 59, 5, 100000]]}]}
        publish_bundle(root, data)
        return data

    def test_old_month_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            self.assertEqual(verify_fresh(root, '2026-10'), '2026-10')
            with self.assertRaises(DataError):
                verify_fresh(root, '2026-11')

    def test_stage_contains_only_live_public_files_and_detects_corrupt_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / 'supabase').mkdir()
            (root / 'supabase/setup.sql').write_text('excluded')
            dest = stage_site(root)
            self.assertTrue((dest / 'index.html').exists())
            self.assertTrue((dest / 'config/supabase.js').exists())
            self.assertFalse((dest / 'config/not-public.txt').exists())
            self.assertFalse((dest / 'supabase').exists())
            self.assertFalse((dest / 'data/site-data.previous.json').exists())
            manifest = json.loads((dest / 'data/site-data.json').read_text())
            part = manifest['_storage']['parts'][0]['file']
            self.assertTrue((dest / 'data' / part).exists())
            (root / 'data' / part).write_text('corrupt')
            with self.assertRaises(DataError):
                stage_site(root)

    def client(self, effects):
        client = MagicMock()
        client.open.side_effect = effects
        return client

    @patch('gyeonggi_public.time.sleep')
    @patch('gyeonggi_public.urllib.request.build_opener')
    def test_transient_portal_failure_retries_then_parses_token(self, opener, sleep):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'<input name="_csrf" value="test">'
        opener.return_value = self.client([urllib.error.HTTPError('url',503,'unavailable',{},None),response])
        self.assertEqual(PublicClient().token, 'test')
        self.assertEqual(opener.return_value.open.call_count, 2)
        sleep.assert_called_once()

    @patch('gyeonggi_public.time.sleep')
    @patch('gyeonggi_public.urllib.request.build_opener')
    def test_permanent_portal_failure_does_not_loop(self, opener, sleep):
        opener.return_value = self.client([urllib.error.HTTPError('url',403,'denied',{},None)])
        with self.assertRaisesRegex(DataError, 'HTTP 403'):
            PublicClient()
        sleep.assert_not_called()

    @patch('gyeonggi_public.time.sleep')
    @patch('gyeonggi_public.urllib.request.build_opener')
    def test_service_failure_is_bounded(self, opener, sleep):
        opener.return_value = self.client([urllib.error.HTTPError('url',503,'unavailable',{},None)]*3)
        with self.assertRaisesRegex(DataError, 'HTTP 503'):
            PublicClient()
        self.assertEqual(opener.return_value.open.call_count, 3)


if __name__ == '__main__':
    unittest.main()
