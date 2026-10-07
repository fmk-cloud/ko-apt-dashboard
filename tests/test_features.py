import sys,copy,unittest,io,csv,zipfile,json,tempfile
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from features_data import assign_far,collect_rent,read_archive,archive_index,FIELDS,enrich
from pipeline import DataError
from seoul_public import run_public
class FeatureTests(unittest.TestCase):
 def setUp(self):
  self.c={'id':'A1','region':'영등포구','name':'검증아파트','official_name':'검증아파트','legal_dong':'당산동','build_year':2000,'households':500,'address':'서울특별시 영등포구 검증로 10'}
  self.b=[{'complex_id':'A1','legal_dong':'당산동','jibun':'1','trade_name':'검증아파트','build_year':2000}]
  self.f={'sgg_cd_nm':'서울특별시 영등포구','stdg_cd_nm':'당산동','mn_lotno':'1','sub_lotno':'0','na_road_cd_nm':'검증로','na_mn_lotno':'10','na_sub_lotno':'0','hh_cnt':500,'use_aprv_ymd':'2000-01-01','fart':'300','siar':'10000','fart_cmpttn_gfa':'30000','mn_usg_cd_nm':'공동주택','bdrg_sn':100000000000000000001,'plat_plc':'서울특별시 영등포구 당산동 1'}
  self.row={'cgg_cd':'11560','bldg_usg':'아파트','rent_se':'전세','rtfe':'0','ctrt_day':'20260915','stdg_nm':'당산동','mno':'0001','sno':'0000','bldg_nm':'검증아파트','arch_yr':'2000','rent_area':'59.9','grfe':'70000','flr':'5','new_updt_yn':'신규','ctrt_prd':'26.09~28.09','ctrt_updt_use_yn':''}
 def far(self,c=None,f=None):
  rows=[dict(self.f,na_mn_lotno=str(100+i),mn_lotno=str(100+i)) for i in range(100)]+[f or self.f]
  return assign_far([c or self.c],rows,self.b)
 def test_far_address_households_and_long_id(self):
  r=self.far();self.assertEqual(r['verified'],1);self.assertEqual(self.c['far'],300);self.assertEqual(self.c['far_info']['ledger_id'],'100000000000000000001')
 def test_wrong_households_not_used(self):
  # Include one valid second complex so the overall source can pass while A1 remains unconfirmed.
  c2=dict(self.c,id='A2',address='서울특별시 영등포구 검증로 11');f2=dict(self.f,na_mn_lotno='11',mn_lotno='2')
  rows=[dict(self.f,hh_cnt=900),f2]+[dict(self.f,mn_lotno=str(i+100),na_mn_lotno=str(i+100)) for i in range(100)]
  result=assign_far([self.c,c2],rows,self.b);self.assertEqual(result['verified'],1);self.assertIsNone(self.c['far'])
 def test_zero_and_inconsistent_far_cannot_be_promoted(self):
  for f in [dict(self.f,fart='0'),dict(self.f,fart='500')]:
   with self.assertRaises(DataError):self.far(f=f)
 def test_full_row_duplicates_removed_but_distinct_period_retained(self):
  rows=[self.row,dict(self.row),dict(self.row,ctrt_prd='26.10~28.10')]
  r=collect_rent([self.c],rows,self.b,'2026-01','2026-09');self.assertEqual(r['rows'],2);self.assertEqual(r['stats']['identical_public_rows_removed'],1)
 def test_rent_excludes_monthly_and_matches_dong_parcel_year(self):
  rows=[self.row,dict(self.row,rtfe='10'),dict(self.row,stdg_nm='양평동'),dict(self.row,mno='2'),dict(self.row,arch_yr='2020')]
  r=collect_rent([self.c],rows,self.b,'2026-01','2026-09');self.assertEqual(r['rows'],1)
 def test_unknown_floor_kept_as_unknown_not_zero_or_high_floor(self):
  r=collect_rent([self.c],[dict(self.row,flr=None)],self.b,'2026-01','2026-09');self.assertIsNone(self.c['jeonse_tx'][0][2])
 def test_renewal_label_retained(self):
  collect_rent([self.c],[dict(self.row,new_updt_yn='갱신',ctrt_updt_use_yn='○')],self.b,'2026-01','2026-09');self.assertEqual(self.c['jeonse_tx'][0][4:6],['갱신','○'])
 def test_archive_parse_filters_exact_district(self):
  text=io.StringIO();w=csv.DictWriter(text,fieldnames=list(FIELDS));w.writeheader()
  row={k:self.row.get(v,'') for k,v in FIELDS.items()};w.writerow(row);w.writerow(dict(row,자치구코드='11440',자치구명='마포구') if '자치구명' in FIELDS else dict(row,자치구코드='11440'))
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('data.csv',text.getvalue().encode('utf-8-sig'))
  self.assertEqual(len(read_archive(b.getvalue())),1)
 def test_archive_links_not_hardcoded(self):
  html='''<tr><td><span title="서울특별시_전월세가_2027.zip" onclick="downloadFile('99');">file</span></td><td>2028.02.04.</td></tr>'''
  self.assertEqual(archive_index(html)[2027],{'seq':'99','published':'2028.02.04.'})
 def test_feature_failure_preserves_prior_features_but_updates_sales(self):
  for previously_enabled in [True,False]:
   with self.subTest(previously_enabled=previously_enabled),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);(root/'data').mkdir();(root/'config').mkdir()
    c=dict(self.c,far=300,far_info={'status':'verified'},jeonse_tx=[['2026-09-15',59.9,5,70000,'신규','']],tx=[['2026-09-01',59.9,5,100000]])
    old={'meta':{'features':{'far':previously_enabled,'gap':previously_enabled},'far_verified_count':1,'jeonse_rows':1},'complexes':[c]}
    new={'meta':{'loaded_regions':['영등포구']},'complexes':[dict(self.c,tx=[['2026-09-01',59.9,5,110000]])]}
    files={'data/site-data.json':old,'data/complexes.json':[self.c],'config/catalog-exclusions.json':[],'config/seoul-bindings.json':self.b,'config/settings.json':{'start_month':'2026-09','regions':[{'code':'11560','name':'영등포구'}]}}
    for name,value in files.items():(root/name).write_text(json.dumps(value))
    before=(root/'data/site-data.json').read_bytes();html='<script>window.__EMBEDDED_DATA__={};</script>';(root/'index.html').write_text(html)
    report={'complex_count':1,'trade_count':1,'unresolved_complexes':[]}
    with patch('seoul_public.normalize_master',return_value=[self.c]),patch('seoul_public.collect',return_value=(new,report)),patch('seoul_public.enrich',side_effect=DataError('source unavailable')):
     if previously_enabled:
      run_public(root,master_rows=[],trade_rows=[])
      published=json.loads((root/'data/site-data.json').read_text());self.assertEqual(published['meta']['feature_update']['status'],'preserved')
      self.assertEqual(published['complexes'][0]['far'],300);self.assertEqual(published['complexes'][0]['jeonse_tx'],c['jeonse_tx']);self.assertEqual(published['complexes'][0]['tx'][0][3],110000)
      self.assertEqual((root/'data/site-data.previous.json').read_text(),json.dumps(old,ensure_ascii=False,indent=2)+'\n')
     else:
      with self.assertRaises(DataError):run_public(root,master_rows=[],trade_rows=[])
      self.assertEqual((root/'data/site-data.json').read_bytes(),before);self.assertEqual((root/'index.html').read_text(),html)
 def test_rent_loss_gate_prevents_silent_partial_replacement(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'data').mkdir();(root/'config').mkdir();(root/'config/seoul-bindings.json').write_text(json.dumps(self.b))
   old={'meta':{'features':{'gap':True}},'complexes':[dict(self.c,jeonse_tx=[['2026-09-01',59.9,5,70000,'신규','']]*10)]}
   (root/'data/site-data.json').write_text(json.dumps(old));d={'meta':{'min_month':'2026-09','current_month':'2026-09'},'complexes':[self.c]}
   with patch('features_data.assign_far',return_value={'verified':1}):
    with self.assertRaisesRegex(DataError,'급감'):enrich(root,d,None,{'far':[],'live':[self.row],'archives':{},'current_year':2026})
if __name__=='__main__':unittest.main()
