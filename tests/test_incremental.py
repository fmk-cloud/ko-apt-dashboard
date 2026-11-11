import copy,datetime as dt,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import gyeonggi_public as gg
from collection_cache import load_response,save_response
from refresh_window import refresh_start
from pipeline import DataError

class IncrementalTests(unittest.TestCase):
 def snapshot(self,month='2026-09'):
  return {'meta':{'source_verified':True,'provider':'seoul_gyeonggi_official','current_month':month}}
 def test_verified_history_excludes_2024_without_holes(self):
  self.assertEqual(refresh_start(self.snapshot(),'2024-01','2026-10'),'2025-11')
  self.assertEqual(refresh_start(self.snapshot('2024-08'),'2024-01','2026-10'),'2024-09')
  self.assertEqual(refresh_start(self.snapshot(),'2024-01','2026-10',True),'2024-01')
  self.assertEqual(refresh_start({},'2024-01','2026-10'),'2024-01')
  self.assertEqual(refresh_start(self.snapshot('2026-12'),'2024-01','2027-01'),'2026-02')
 def test_queries_are_bounded_by_requested_months(self):
  calls=[]
  class Client:
   def trades(self,code,dong,year,**args):calls.append((year,args));return {'rtlpList':[]},'a'*64
  plan=[dict(code='41590',dong_code='10900',dong='신동',region='화성시',ids=['A1'],old=True)]
  with patch.object(gg,'PublicClient',Client),patch('builtins.print'):
   gg.download_responses(plan,'2025-11','2026-10',ranged=True,max_workers=1)
  self.assertEqual(calls,[(2025,dict(start='20251101',end='20251231',old=True)),(2026,dict(start='20260101',end='20261031',old=True))])
 def fixture(self):
  cat=[dict(id='A1',name='테스트',region='광명시',legal_dong='광명동',aliases=['테스트'],build_year=1998,households=500,metadata_parcels=[['1','309-1']])]
  row={'PNU':'4121010100103090001','KAB_APTNM':'테스트','MVIN_YM':'1998','BLDG_MUSE_CD':'02001','BLDG_AREA':59.96,'A11':'10.04','A21':'41000','A31':'7','DPOS_GBN':'','B11':'10.12','B21':'30000','B31':'9'}
  plan=[dict(code='41210',dong_code='10100',region='광명시',dong='광명동',ids=['A1'])]
  return cat,row,plan
 def test_recent_cancellation_replaced_old_history_retained_no_duplicates(self):
  cat,row,plan=self.fixture()
  old=copy.deepcopy(cat[0]);old.update(coverage_from='2024-01',tx=[['2025-09-09',59.96,7,39000,'광명동','','309-1'],['2026-10-04',59.96,7,41000,'광명동','','309-1']],jeonse_tx=[['2025-09-09',59.96,7,28000,'미상','','']])
  rows=[dict(row,DPOS_GBN='2026.11.01'),dict(row,A11='10.06',A21='42000',B11='',B21='')]
  response=[dict(code='41210',dong_code='10100',year=2026,rows=rows)]
  cs,_=gg.collect(cat,response,plan,'2026-10','2026-10',[old],preserve_before=True)
  self.assertEqual([t[0] for t in cs[0]['tx']],['2025-09-09','2026-10-06'])
  self.assertEqual(len(cs[0]['jeonse_tx']),2)
  self.assertEqual(cs[0]['coverage_from'],'2024-01')
  again,_=gg.collect(cat,response,plan,'2026-10','2026-10',cs,preserve_before=True)
  self.assertEqual(cs,again)
 def test_history_does_not_mask_recent_data_collapse(self):
  cat,row,plan=self.fixture();old=copy.deepcopy(cat[0])
  old['tx']=[['2024-01-01',59,5,100000]]*1000+[['2026-10-01',59,5,100000]]*10
  with self.assertRaisesRegex(DataError,'급감'):
   gg.collect(cat,[dict(code='41210',dong_code='10100',year=2026,rows=[row])],plan,'2026-10','2026-10',[old],preserve_before=True)
 def test_empty_month_and_wrong_dong_cannot_publish(self):
  cat,row,plan=self.fixture()
  with self.assertRaisesRegex(DataError,'월 전체 누락'):
   gg.collect(cat,[dict(code='41210',dong_code='10100',year=2026,rows=[])],plan,'2026-10','2026-10',preserve_before=True)
  with self.assertRaisesRegex(DataError,'법정동'):
   gg.collect(cat,[dict(code='41210',dong_code='10100',year=2026,rows=[dict(row,PNU='4121010200103090001')])],plan,'2026-10','2026-10')
 def test_new_complex_history_may_have_empty_preconstruction_months(self):
  cat,row,plan=self.fixture()
  cs,_=gg.collect(cat,[dict(code='41210',dong_code='10100',year=2026,rows=[row])],plan,'2024-01','2026-10',require_months=False)
  self.assertEqual(len(cs[0]['tx']),1)
 def test_history_identity_conflict_stops_merge(self):
  cat,row,plan=self.fixture();old=dict(cat[0],build_year=2000,tx=[['2024-01-01',59,5,100000]])
  with self.assertRaisesRegex(DataError,'정보 충돌'):
   gg.collect(cat,[dict(code='41210',dong_code='10100',year=2026,rows=[row])],plan,'2026-10','2026-10',[old],preserve_before=True)
 def test_cache_hash_ttl_query_and_future_time(self):
  with tempfile.TemporaryDirectory() as folder:
   p=Path(folder)/'x.json';q={'start':'20261001','old':False};now=dt.datetime.now(dt.timezone.utc)
   save_response(p,q,[{'x':1}],'a'*64)
   self.assertIsNotNone(load_response(p,q))
   self.assertIsNone(load_response(p,dict(q,old=True)))
   self.assertIsNone(load_response(p,q,now+dt.timedelta(hours=49)))
   self.assertIsNone(load_response(p,q,now-dt.timedelta(hours=1)))
   data=json.loads(p.read_text());data['rows'][0]['x']=9;p.write_text(json.dumps(data));self.assertIsNone(load_response(p,q))
 def test_failed_split_resumes_successful_ranges(self):
  with tempfile.TemporaryDirectory() as folder:
   client=gg.PublicClient.__new__(gg.PublicClient);client.range_cache=Path(folder);calls=[];fail=[True]
   def post(path,args,**kwargs):
    first=dt.datetime.strptime(args['startDate'],'%Y%m%d').date();last=dt.datetime.strptime(args['endDate'],'%Y%m%d').date();calls.append((first,last))
    if (last-first).days>=7 or (fail[0] and first.day>=17):raise DataError('HTTP 503')
    obj={'rtlpList':[{'first':str(first),'last':str(last)}]};return obj,json.dumps(obj).encode()
   client.post=post
   with self.assertRaisesRegex(DataError,'HTTP 503'):client.trades('41590','10900',2026,start='20261001',end='20261031')
   successful_left=[json.loads(p.read_text()) for p in Path(folder).glob('*.json')]
   self.assertTrue(successful_left);self.assertFalse(any(x['query']['end']=='20261031' for x in successful_left))
   fail[0]=False;calls.clear();obj,_=client.trades('41590','10900',2026,start='20261001',end='20261031')
   self.assertGreater(client.cache_hits,0)
   self.assertFalse(any(a.day==1 and b.day<=16 for a,b in calls))
   dates=[]
   for row in obj['rtlpList']:
    a=dt.date.fromisoformat(row['first']);b=dt.date.fromisoformat(row['last']);dates += [a+dt.timedelta(days=i) for i in range((b-a).days+1)]
   self.assertEqual(len(dates),31);self.assertEqual(len(set(dates)),31)
   calls.clear();client.trades('41590','10900',2026,start='20261001',end='20261031');self.assertEqual(calls,[])
 def test_cached_child_age_not_reset_in_parent(self):
  with tempfile.TemporaryDirectory() as folder:
   client=gg.PublicClient.__new__(gg.PublicClient);client.range_cache=Path(folder)
   stamp=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=47)).isoformat()
   query=dict(code='41590',dong='10900',year=2026,start='20261001',end='20261016',old=False)
   p=Path(folder)/'41590-10900-2026-20261001-20261016-False.json';save_response(p,query,[], 'a'*64,stamp)
   def post(path,args,**kwargs):
    if args['startDate']=='20261001':raise DataError('large')
    return {'rtlpList':[]},b'[]'
   client.post=post;client.trades('41590','10900',2026,start='20261001',end='20261031')
   parent=Path(folder)/'41590-10900-2026-20261001-20261031-False.json'
   self.assertEqual(json.loads(parent.read_text())['checked_at'],stamp)
 def test_seoul_lease_fallback_does_not_mislabel_gyeonggi_month(self):
  from update_all import merge_data
  seoul={'meta':{'loaded_regions':['영등포구'],'current_month':'2026-10','min_month':'2024-01','sources':{},'region_feature_counts':{},'jeonse_to':'2026-09'},'complexes':[dict(id='S1',region='영등포구',name='서울단지',households=300,tx=[],jeonse_tx=[])]}
  gg=[dict(id='G1',region='광명시',name='경기단지',households=300,tx=[],jeonse_tx=[['2026-10-01',59,5,30000,'미상','','']])]
  d,_=merge_data(seoul,gg,{'gyeonggi':{'refresh':{'to':'2026-10'}}},{},[])
  self.assertEqual(d['meta']['jeonse_to'],'2026-10');self.assertEqual(d['meta']['seoul_jeonse_to'],'2026-09')
 def test_workflow_calendar_outputs_cache_month(self):
  import os,subprocess
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as folder:
   output=Path(folder)/'outputs'
   result=subprocess.run([sys.executable,str(root/'scripts/schedule_due.py')],env=dict(os.environ,GITHUB_OUTPUT=str(output),GITHUB_EVENT_NAME='workflow_dispatch'),capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
   values=dict(line.split('=',1) for line in output.read_text().splitlines())
   self.assertEqual(values['due'],'true');self.assertRegex(values['target_month'],r'^\d{4}-\d{2}$')
 def test_download_error_preserves_underlying_reason(self):
  class Client:
   def trades(self,*a,**k):raise DataError('HTTP 503 at 20241001~20241007')
  plan=[dict(code='41590',dong_code='10900',region='화성시',dong='신동',ids=['A1'])]
  with patch.object(gg,'PublicClient',Client):
   with self.assertRaisesRegex(DataError,'화성시 신동 2024.*HTTP 503'):
    gg.download_responses(plan,'2024-10','2024-10',ranged=True,max_workers=1)

if __name__=='__main__':unittest.main()
