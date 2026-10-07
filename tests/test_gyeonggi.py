import copy,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pipeline import DataError
from kapt_public import normalize_gyeonggi,legal_parcels,supplement_seoul
import gyeonggi_public as gg

class GyeonggiTests(unittest.TestCase):
 def metadata(self,city='광명시',cid='A1',hh='500'):
  return {'시도':'경기도','시군구':city,'읍면':'','동리':'광명동','단지코드':cid,'단지명':'테스트아파트','단지분류':'아파트','분양형태':'분양','법정동주소':f'경기도 {city} 광명동 309-1 테스트아파트','도로명주소':'도로 1','사용승인일':'19980501','세대수':hh,'최고층수':'25'}
 def test_under_300_and_pure_rental_never_enter_catalog(self):
  rows=[self.metadata(city,city) for city in gg.CITIES];rows+=[dict(self.metadata(cid='small',hh='299')),dict(self.metadata(cid='rental'),분양형태='임대')]
  rows=[self.metadata(city,city+str(i)) for city in gg.CITIES for i in range(5)]+rows[-2:]
  cs,held=normalize_gyeonggi(rows,gg.CITIES);self.assertEqual(len(cs),25);self.assertNotIn('small',{c['id'] for c in cs});self.assertNotIn('rental',{c['id'] for c in cs})
 def test_duplicate_parcel_rows_do_not_duplicate_complexes(self):
  rows=[self.metadata(city,city+str(i)) for city in gg.CITIES for i in range(5)];rows.append(dict(rows[0],최고층수='26'))
  cs,_=normalize_gyeonggi(rows,gg.CITIES);self.assertEqual(len(cs),25)
 def test_combined_management_households_are_held(self):
  rows=[self.metadata(city,city+str(i)) for city in gg.CITIES for i in range(5)]
  combined=dict(self.metadata(cid='combined'),법정동주소='경기도 광명시 광명동 309-1,경기도 광명시 광명동 310 테스트아파트')
  cs,held=normalize_gyeonggi(rows+[combined],gg.CITIES);self.assertNotIn('combined',{c['id'] for c in cs});self.assertEqual(held[0]['id'],'combined')
 def test_cancelled_sale_does_not_discard_independent_jeonse(self):
  cat=[dict(id='A1',name='테스트',region='광명시',legal_dong='광명동',aliases=['테스트'],build_year=1998,households=500,metadata_parcels=[['1','309-1']])]
  row={'PNU':'4121010100103090001','KAB_APTNM':'테스트','MVIN_YM':'1998','BLDG_MUSE_CD':'02001','BLDG_AREA':59.96,'A11':'09.04','A21':'41,000','A31':'07','A41':'101','DPOS_GBN':'25.12.12','B11':'09.12','B21':'30,000','B31':'09','C21':'1,000(100)'}
  good=dict(row,DPOS_GBN='',A21='42,000',B11='',B21='')
  plan=[{'code':'41210','dong_code':'10100','region':'광명시','dong':'광명동','ids':['A1']}]
  with patch.object(gg,'CITIES',['광명시']):cs,report=gg.collect(cat,[{'code':'41210','dong_code':'10100','year':2025,'rows':[row,good,row]}],plan,'2025-09','2025-09')
  self.assertEqual(len(cs[0]['tx']),1);self.assertEqual(cs[0]['tx'][0][3],42000);self.assertEqual(len(cs[0]['jeonse_tx']),1);self.assertEqual(cs[0]['jeonse_tx'][0][4],'미상');self.assertEqual(cs[0]['jeonse_tx'][0][3],30000)
 def test_missing_parcel_uses_unique_full_name_not_similarity(self):
  c={'id':'A1','name':'과천푸르지오라비엔오','region':'과천시','aliases':['과천푸르지오라비엔오'],'build_year':2021,'metadata_parcels':[]}
  key=('41290','10300','1','0',2021,gg.norm(c['name']))
  found,method=gg.find_complex([c],key,'과천시');self.assertEqual(found['id'],'A1');self.assertEqual(method,'exact_name_dong_year_missing_parcel')
  wrong=(*key[:5],gg.norm('과천푸르지오벨라르테'));self.assertIsNone(gg.find_complex([c],wrong,'과천시')[0])
  self.assertIsNone(gg.find_complex([c,dict(c,id='A2')],key,'과천시')[0])
 def test_conflicting_nonempty_parcels_never_use_name_only(self):
  c={'id':'A1','name':'과천푸르지오써밋','aliases':['과천푸르지오써밋'],'build_year':2020,'metadata_parcels':[['1','37']]}
  self.assertIsNone(gg.find_complex([c],('41290','10400','1','137',2020,gg.norm(c['name'])),'과천시')[0])
 def test_village_name_order_keeps_phase_numbers_and_parcel(self):
  c=dict(id='A1',name='정자한솔마을주공4차',region='성남시',legal_dong='정자동',aliases=['정자한솔마을주공4차'],build_year=1994,metadata_parcels=[['1','102']])
  k=('41135','10300','1','102',1994,gg.norm('한솔마을(4단지)(주공)'))
  self.assertEqual(gg.find_complex([c],k,'성남시')[0]['id'],'A1')
  self.assertIsNone(gg.find_complex([c],(*k[:5],gg.norm('한솔마을(5단지)(주공)')),'성남시')[0])
  self.assertIsNone(gg.find_complex([c],(*k[:3],'103',*k[4:]),'성남시')[0])
 def test_yearly_contract_dates_are_validated(self):
  self.assertEqual(gg.disclosed_date('09.04',2025),'2025-09-04');self.assertEqual(gg.disclosed_date('25.09.04',2026),'2025-09-04')
  with self.assertRaises(DataError):gg.disclosed_date('02.30',2025)
 def test_large_old_eup_completed_years_use_all_twelve_months(self):
  calls=[]
  class Client:
   def trades(self,code,dong,year,**args):
    calls.append((year,args));return {'rtlpList':[{'year':year,'start':args.get('start')}]},'a'*64
  plan=[dict(code='41590',dong_code='25900',dong='향남읍',region='화성시',old=True,old_eup=True)]
  with patch.object(gg,'PublicClient',Client),patch('builtins.print'):
   responses=gg.download_responses(plan,'2024-01','2026-09',max_workers=1)
  for year in (2024,2025):
   self.assertEqual([args['start'] for y,args in calls if y==year],[f'{year}{month:02}01' for month in range(1,13)])
   self.assertTrue(all(args['old'] for y,args in calls if y==year))
   self.assertEqual(len(next(r['rows'] for r in responses if r['year']==year)),12)
  self.assertEqual(next(args for y,args in calls if y==2026),{'old':True})
 def test_eup_response_uses_disclosed_ri_not_query_ri(self):
  base=dict(name='테스트단지',region='화성시',aliases=['테스트단지'],build_year=1998,households=500,metadata_parcels=[['1','309-1']])
  cat=[dict(base,id='A1',legal_dong='남양읍 남양리'),dict(base,id='A2',legal_dong='남양읍 신남리')]
  row={'PNU':'4159125623103090001','UMD_NM':'(남양읍 신남리)','KAB_APTNM':'테스트단지','MVIN_YM':'1998','BLDG_MUSE_CD':'02001','BLDG_AREA':59.96,'A11':'09.04','A21':'41,000','A31':'07','B11':'09.12','B21':'30,000','B31':'09'}
  plan=[dict(code='41591',dong_code='25621',region='화성시',dong='남양읍 남양리',eup_scope=True,eup_name='남양읍',ids=['A1','A2'])]
  cs,_=gg.collect(cat,[dict(code='41591',dong_code='25621',year=2025,rows=[row])],plan,'2025-09','2025-09')
  self.assertEqual(len(cs[0]['tx']),0);self.assertEqual(len(cs[1]['tx']),1);self.assertEqual(cs[1]['tx'][0][4],'남양읍 신남리')
 def test_mismatched_households_cannot_supplement_seoul_parcel(self):
  c={'id':'A1','region':'강남구','legal_dong':'개포동','households':500,'build_year':1998,'metadata_jibun':''}
  r=dict(self.metadata(),시도='서울특별시',시군구='강남구',동리='개포동',법정동주소='서울특별시 강남구 개포동 309-1 테스트',세대수='501')
  self.assertEqual(supplement_seoul([c],[r]),[]);self.assertEqual(c['metadata_jibun'],'')
if __name__=='__main__':unittest.main()
