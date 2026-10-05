import sys,json,copy,tempfile,unittest,datetime as dt
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from pipeline import DataError,normalize_master,month_range
from seoul_public import collect,run_public,download
from embed_data import embedded_html
from schedule_due import due
ROOT=Path(__file__).resolve().parents[1]
class PipelineTests(unittest.TestCase):
 def setUp(self):
  self.c={'id':'A1','name':'검증단지','official_name':'검증단지','region':'영등포구','households':300,'legal_dong':'당산동','build_year':2000}
  self.row={'cgg_cd':'11560','rcpt_yr':'2026','bldg_usg':'아파트','rght_se':None,'ctrt_day':'20260910','stdg_nm':'당산동','mno':'0001','sno':'0000','bldg_nm':'검증단지','arch_yr':'2000','thing_amt':'100000','arch_area':59.9,'flr':5,'rtrcn_day':None}
  self.rows=[dict(self.row) for _ in range(100)]
 def collect(self,rows=None,old=None,start='2026-09',end='2026-09'):
  return collect([self.c],self.rows if rows is None else rows,[],old or {},start,end)
 def test_same_day_equal_trades_not_deduplicated_and_refresh_idempotent(self):
  d,_=self.collect();self.assertEqual(len(d['complexes'][0]['tx']),100)
  again,_=self.collect(old=d);self.assertEqual(again['complexes'],d['complexes'])
 def test_cancelled_and_rights_are_excluded(self):
  self.rows[0]['rtrcn_day']='20261001';self.rows[1]['rght_se']='분양권';self.rows[2]['rght_se']='입주권'
  d,_=self.collect();self.assertEqual(len(d['complexes'][0]['tx']),97)
 def test_new_cancellation_removes_existing_trade(self):
  d,_=self.collect();self.rows[0]['rtrcn_day']='20261001'
  newer,_=self.collect(old=d);self.assertEqual(len(newer['complexes'][0]['tx']),99)
 def test_changed_names_stop_promotion(self):
  old,_=self.collect()
  for r in self.rows[:90]:r['bldg_nm']='동명이인후보'
  with self.assertRaises(DataError):self.collect(old=old)
 def test_wrong_dong_not_fuzzy_matched(self):
  for r in self.rows:r['stdg_nm']='대림동'
  with self.assertRaises(DataError):self.collect()
 def test_missing_month_and_other_district_stop(self):
  with self.assertRaises(DataError):self.collect(start='2026-08')
  self.rows[0]['cgg_cd']='11440'
  with self.assertRaises(DataError):self.collect()
 def test_old_history_retained_with_visible_flag(self):
  d,_=self.collect();d['complexes'][0]['tx'].append(['2025-01-10',59.9,5,90000,'당산동','','1'])
  # Receipt-year rollover: earlier source years no longer present.
  rows=[]
  for month in range(1,10):
   rows.extend([dict(self.row,ctrt_day=f'2026{month:02}10') for _ in range(100)])
  n,_=self.collect(rows,d,'2025-01')
  self.assertTrue(n['meta']['older_history_frozen']);self.assertEqual(len(n['complexes'][0]['tx']),901)
 def test_broken_download_does_not_overwrite_data_or_html(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'data').mkdir()
   for name in ['site-data.json','complexes.json']:(root/'data'/name).write_bytes((ROOT/'data'/name).read_bytes())
   (root/'index.html').write_text('unchanged')
   before=(root/'data/site-data.json').read_bytes()
   for bad in [b'<html>maintenance</html>',b'{"DATA":[]}',b'{}']:
    with self.assertRaises(DataError):run_public(root,fetch=lambda *args:bad)
    self.assertEqual(before,(root/'data/site-data.json').read_bytes());self.assertEqual((root/'index.html').read_text(),'unchanged')
 def test_household_threshold_and_rental_exclusion(self):
  rows=[{'apt_cd':str(i),'apt_nm':str(i),'sgg_addr':'영등포구','tnohsh':300,'cmpx_clsf':'아파트','hh_type':'분양'} for i in range(52)]
  rows[0]['tnohsh']=299;rows[1]['hh_type']='임대'
  self.assertEqual(len(normalize_master(rows,[])),50)
  rows[2]['tnohsh']=None
  with self.assertRaises(DataError):normalize_master(rows,[])
 def test_incomplete_master_rejected(self):
  with self.assertRaises(DataError):normalize_master([],[])
 def test_embed_escapes_script_and_backslashes(self):
  d={'complexes':[{'name':'</script><script>bad()\\path'}]}
  html=embedded_html('<script>window.__EMBEDDED_DATA__={};</script>',d)
  self.assertEqual(html.count('</script>'),1)
  self.assertEqual(json.loads(html.split('=',1)[1].split(';</script>')[0]),d)
 def test_scheduler_handles_short_month_and_year_boundary(self):
  for day in ['2026-02-28','2028-02-29','2026-04-30','2026-12-31']:
   self.assertTrue(due('schedule',dt.datetime.fromisoformat(day+'T19:00:00+00:00')))
  self.assertFalse(due('schedule',dt.datetime.fromisoformat('2026-10-28T19:00:00+00:00')))
  self.assertTrue(due('workflow_dispatch'))
  self.assertEqual(month_range('2025-12','2026-02'),['2025-12','2026-01','2026-02'])
if __name__=='__main__':unittest.main()
