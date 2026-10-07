import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from dataset_storage import publish_bundle,parse_part
from pipeline import read_json,DataError
class StorageTests(unittest.TestCase):
 def test_region_parts_preserve_original_complex_order(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'index.html').write_text('<script>window.__EMBEDDED_DATA__={};</script>')
   d=self.data();a=d['complexes'][0];d['complexes']=[a,dict(a,id='A2',region='마포구'),dict(a,id='A3')];d['meta'].update(loaded_regions=['영등포구','마포구'],complex_count=3)
   publish_bundle(root,d);self.assertEqual(read_json(root/'data/site-data.json'),d)
 def data(self,price=10000):
  return {'meta':{'loaded_regions':['영등포구'],'complex_count':1},'complexes':[{'id':'A1','name':'검증 </script> 단지','region':'영등포구','households':300,'tx':[['2025-09-01',59.9,7,price]]}]}
 def test_split_roundtrip_keeps_previous_snapshot_and_script_escaping(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'index.html').write_text('<script>window.__EMBEDDED_DATA__={};</script>')
   old=self.data();new=self.data(12000);publish_bundle(root,new,previous=old)
   self.assertEqual(read_json(root/'data/site-data.json'),new);self.assertEqual(read_json(root/'data/site-data.previous.json'),old)
   p=json.loads((root/'data/site-data.json').read_text())['_storage']['parts'][0]['file'];body=(root/'data'/p).read_text();self.assertNotIn('</script>',body);self.assertIn('\\u003c',body)
   self.assertIn('REGIONAL_DATA_START',(root/'index.html').read_text())
   publish_bundle(root,self.data(13000),previous=new);self.assertEqual(read_json(root/'data/site-data.previous.json'),new)
   self.assertEqual(len(list((root/'data/regions').glob('*.js'))),2)
 def test_missing_or_changed_part_stops_loading_instead_of_using_partial_data(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'index.html').write_text('<script>window.__EMBEDDED_DATA__={};</script>');publish_bundle(root,self.data())
   p=json.loads((root/'data/site-data.json').read_text())['_storage']['parts'][0]['file'];path=root/'data'/p;path.write_text(path.read_text().replace('10000','10001'))
   with self.assertRaises(DataError):read_json(root/'data/site-data.json')
   path.unlink()
   with self.assertRaises(DataError):read_json(root/'data/site-data.json')
if __name__=='__main__':unittest.main()
