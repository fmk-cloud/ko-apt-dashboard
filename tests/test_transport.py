import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from transport_utils import lines
from update_transport import apply_transport
from pipeline import DataError
class TransportTests(unittest.TestCase):
 def test_airport_station_name_is_not_arex(self):
  self.assertEqual(lines({'route':'subway','name':'서울 지하철 9호선 김포공항 - 중앙보훈병원'}),{'9'})
  self.assertEqual(lines({'route':'train','name':'공항철도 인천공항 - 서울역'}),{'공항'})
 def test_sillim_station_name_is_not_sillim_line(self):
  self.assertEqual(lines({'route':'subway','name':'서울 지하철 2호선 신림역'}),{'2'})
  self.assertEqual(lines({'route':'light_rail','name':'신림선'}),{'신림'})
 def test_shinbundang_is_not_bundang(self):
  self.assertEqual(lines({'name':'신분당선','route':'train'}),{'신분당'})
  self.assertEqual(lines({'name':'수인분당선','route':'train'}),{'수인분당'})
 def test_missing_line_is_not_guessed_from_numeric_station_ref(self):
  self.assertEqual(lines({'name':'강변','ref':'214','station':'subway'}),set())
  self.assertEqual(lines({'name':'당산','operator':'서울시메트로9호선'}),{'9'})
 def test_gtx_a(self):self.assertEqual(lines({'name':'수도권 광역급행철도 GTX-A','route':'train'}),{'GTX-A'})
 def test_boundary_and_unknown_routes(self):
  # The route result validator should reject an out-of-range link before publishing anything.
  data={'meta':{'loaded_regions':['영등포구'],'complex_count':1,'current_month':'2026-09'},'complexes':[{'id':'A1','name':'테스트','region':'영등포구','households':300,'tx':[]}]}
  row={'name':'당산역','lines':['2','9'],'distance_m':1301,'minutes':20,'method':'osm_walk_network_estimate'}
  links={'meta':{'checked_at':'2026-10-07'},'complexes':{'A1':{'walks':[row]}}}
  with self.assertRaises(DataError):apply_transport(data,links)
  self.assertNotIn('station_walks',data['complexes'][0])
  with self.assertRaises(DataError):apply_transport(data,{'meta':links['meta'],'complexes':{}})
if __name__=='__main__':unittest.main()
