import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pipeline import DataError
from update_all import run_all
from kapt_public import find_attachment,gyeonggi_region_tags
class AllUpdateTests(unittest.TestCase):
 def test_later_source_failure_preserves_entire_live_snapshot(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'data').mkdir();(root/'config').mkdir();(root/'reports').mkdir()
   (root/'data/site-data.json').write_text('{"meta":{"source_verified":true},"complexes":[]}')
   (root/'data/complexes.json').write_text('[]');(root/'index.html').write_text('previous working dashboard')
   (root/'config/settings.json').write_text('{"start_month":"2024-01"}')
   old=(root/'data/site-data.json').read_bytes();html=(root/'index.html').read_bytes()
   with patch('update_all.download_kapt',return_value=([],{})),patch('update_all.normalize_gyeonggi',return_value=([],[])),patch('update_all.PublicClient'),patch('update_all.query_plan',return_value=([],[])),patch('update_all.download_responses',return_value=[]),patch('update_all.collect',return_value=([],{})),patch('update_all.run_public',side_effect=DataError('서울 원자료 실패')):
    with self.assertRaises(DataError):run_all(root)
   self.assertEqual((root/'data/site-data.json').read_bytes(),old);self.assertEqual((root/'index.html').read_bytes(),html)
   self.assertFalse((root/'data/site-data.previous.json').exists());self.assertEqual(json.loads((root/'reports/update-report.json').read_text())['published'],False)
 def test_kapt_uses_latest_basic_file_not_unrelated_or_pinned_attachment(self):
  s='''<li>다른 자료 <a href="javascript:fileDown('999','03','1');">2026-12-01</a></li><li>K-apt 관리비공개의무단지 기본정보(2025.01.01.)<a href="javascript:fileDown('10','03','1');"></a></li><li>K-apt 관리비공개의무단지 기본정보(2026.10.02.)<a href="javascript:fileDown('135807','03','1');"></a></li>'''
  self.assertEqual(find_attachment(s),('135807','1','2026-10-02'))
 def test_subregion_filters_use_real_district_or_legal_dong(self):
  self.assertEqual(gyeonggi_region_tags({'region':'성남시','district':'성남분당구','legal_dong':'정자동'}),['성남시','분당구'])
  self.assertEqual(gyeonggi_region_tags({'region':'화성시','district':'화성동탄구','legal_dong':'반송동'}),['화성시','동탄구','동탄시'])
  self.assertIn('평촌동',gyeonggi_region_tags({'region':'안양시','district':'안양동안구','legal_dong':'평촌동'}))
  self.assertNotIn('평촌동',gyeonggi_region_tags({'region':'안양시','district':'안양동안구','legal_dong':'호계동'}))
if __name__=='__main__':unittest.main()
