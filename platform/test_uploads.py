import base64,io,unittest
from PIL import Image
from uploads import validate_upload
from workflow import normalize_result
class UploadTests(unittest.TestCase):
 def test_valid_png(self):
  b=io.BytesIO();Image.new('RGB',(100,100),'white').save(b,'PNG')
  result=validate_upload('data:image/png;base64,'+base64.b64encode(b.getvalue()).decode())
  self.assertEqual(result['extension'],'png');self.assertEqual(result['bytes'],b.getvalue())
 def test_invalid_payloads(self):
  for v in ['',None,'https://example.com/a.png','data:image/png;base64,aGVsbG8=','data:image/svg+xml;base64,AAAA']:
   with self.assertRaises(ValueError):validate_upload(v)
 def test_mime_mismatch(self):
  b=io.BytesIO();Image.new('RGB',(2,2)).save(b,'PNG')
  with self.assertRaises(ValueError):validate_upload('data:image/jpeg;base64,'+base64.b64encode(b.getvalue()).decode())
 def test_upload_pass(self):
  import json
  self.assertEqual(normalize_result({'upload_status':'PASS','upload_audit_report':json.dumps({'decision':'PASS','needs_human':False,'risks':[]})})['status'],'passed')
 def test_upload_risk_not_pass(self):
  import json
  self.assertEqual(normalize_result({'upload_status':'PASS','upload_audit_report':json.dumps({'decision':'REVISE','needs_human':False,'risks':[{'evidence':'最佳'}]})})['status'],'blocked')
