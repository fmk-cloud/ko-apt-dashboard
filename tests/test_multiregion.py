"""Regional isolation and complete monthly snapshots are required for expansion."""
import copy,sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pipeline import DataError,normalize_master
from seoul_public import collect,run_public
from features_data import collect_rent
class MultiRegionTests(unittest.TestCase):
 def setUp(self):
  self.specs=[{'code':code,'name':name,'minimum_expected_complexes':1} for code,name in [('11560','영등포구'),('11200','성동구'),('11440','마포구')]]
  self.settings={'regions':self.specs,'minimum_households':300,'start_month':'2026-09'}
  self.catalog=[{'id':s['code'],'region':s['name'],'name':'검증단지','official_name':'검증단지','legal_dong':'같은동','households':300,'build_year':2000,'metadata_jibun':'1'} for s in self.specs]
  self.bindings=[{'complex_id':c['id'],'legal_dong':'같은동','jibun':'1','trade_name':'검증단지','build_year':2000} for c in self.catalog]
  self.rows=[{'cgg_cd':s['code'],'rcpt_yr':'2026','bldg_usg':'아파트','rght_se':'소유권','ctrt_day':'20260910','stdg_nm':'같은동','mno':'1','sno':'0','bldg_nm':'검증단지','arch_yr':'2000','thing_amt':str(100000+i*10000),'arch_area':59.9,'flr':5,'rtrcn_day':None} for i,s in enumerate(self.specs) for _ in range(100)]
 def test_same_address_and_name_in_different_districts_never_merge(self):
  d,r=collect(self.catalog,self.rows,self.bindings,{},'2026-09','2026-09',self.settings)
  self.assertEqual(len(d['complexes']),3)
  for i,c in enumerate(d['complexes']):self.assertEqual(len(c['tx']),100);self.assertEqual(c['tx'][0][3],100000+i*10000)
 def test_one_district_missing_entire_month_aborts_all(self):
  with self.assertRaisesRegex(DataError,'자치구/월'):collect(self.catalog,self.rows[:200],self.bindings,{},'2026-09','2026-09',self.settings)
 def test_rent_scope_parameter_filters_new_district_exactly(self):
  c=self.catalog[1];row={'cgg_cd':'11200','bldg_usg':'아파트','rent_se':'전세','rtfe':'0','ctrt_day':'20260915','stdg_nm':'같은동','mno':'1','sno':'0','bldg_nm':'검증단지','arch_yr':'2000','rent_area':'59.9','grfe':'70000','flr':'5'}
  self.assertEqual(collect_rent([c],[row],self.bindings,'2026-09','2026-09','11200')['rows'],1)
  with self.assertRaisesRegex(DataError,'자치구'):collect_rent([c],[dict(row,cgg_cd='11440')],self.bindings,'2026-09','2026-09','11200')
 def test_new_district_feature_failure_does_not_publish_partial_scope(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)
   for folder in ['data','config']: (root/folder).mkdir()
   old={'meta':{'features':{'far':True,'gap':True}},'complexes':[self.catalog[0]]}
   files={'data/site-data.json':old,'data/complexes.json':self.catalog[:1],'config/settings.json':self.settings,'config/catalog-exclusions.json':[],'config/seoul-bindings.json':self.bindings}
   for name,value in files.items():(root/name).write_text(json.dumps(value))
   html='<script>window.__EMBEDDED_DATA__={};</script>';(root/'index.html').write_text(html);before=(root/'data/site-data.json').read_bytes()
   with patch('seoul_public.normalize_master',return_value=self.catalog),patch('seoul_public.enrich',side_effect=DataError('new district feature source unavailable')):
    with self.assertRaises(DataError):run_public(root,master_rows=[],trade_rows=self.rows)
   self.assertEqual((root/'index.html').read_text(),html);self.assertEqual((root/'data/site-data.json').read_bytes(),before)
if __name__=='__main__':unittest.main()
