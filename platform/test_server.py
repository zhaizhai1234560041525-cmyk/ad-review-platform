import io,json,tempfile,time,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import server
PASS={'decision':'PASS','needs_human':False,'risks':[],'summary':'未发现风险'}
def terminal():
 return {'event':'workflow_finished','data':{'status':'succeeded','outputs':{'r0end_status':'PASS','r0end_poster_url':'https://getapib.org/image/test.jpg','r0end_audit_report':json.dumps(PASS)}}}
class Stream:
 def __init__(self,events,raise_after=False):self.events=events;self.raise_after=raise_after
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def __iter__(self):
  for e in self.events:yield ('data: '+json.dumps(e)+'\n').encode();yield b'\n'
  if self.raise_after:raise TimeoutError('after terminal')
class ServerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
  self.patches=[patch.object(server,'DATA',self.path),patch.object(server,'DB',self.path/'test.sqlite3'),patch.object(server,'settings',return_value=('http://example.invalid/v1','test-only-key'))]
  for p in self.patches:p.start()
  server.init_db()
 def tearDown(self):
  for p in self.patches:p.stop()
  self.tmp.cleanup()
 def task(self):
  t={'id':uuid.uuid4().hex,'inputs':{'product_name':'测试','product_facts':'事实','design_request':'设计'},'status':'queued','rounds':[],'events':[],'created_at':time.time()}
  with server.database() as c:c.execute('INSERT INTO tasks VALUES(?,?,?,?)',(t['id'],uuid.uuid4().hex,t['created_at'],json.dumps(t)))
  return t
 def test_terminal_event_stops_consumption(self):
  t=self.task()
  with patch.object(server.urllib.request,'urlopen',return_value=Stream([terminal()],True)),patch.object(server,'archive_image',return_value='/test-image'):
   server.run(t)
  self.assertEqual(server.get_task(t['id'])['status'],'passed')
 def test_premature_stream_end_not_pass(self):
  t=self.task()
  with patch.object(server.urllib.request,'urlopen',return_value=Stream([])):server.run(t)
  self.assertEqual(server.get_task(t['id'])['status'],'failed')
 def test_archive_failure_not_pass(self):
  t=self.task()
  with patch.object(server.urllib.request,'urlopen',return_value=Stream([terminal()])),patch.object(server,'archive_image',side_effect=ValueError('归档失败')):server.run(t)
  self.assertEqual(server.get_task(t['id'])['status'],'failed')
 def test_restart_marks_interrupted(self):
  t=self.task();server.init_db();self.assertEqual(server.get_task(t['id'])['status'],'interrupted')
 def test_only_image_origin_allowed(self):
  for u in ['http://getapib.org/image/a','https://getapib.org.evil.test/image/a','https://127.0.0.1/image/a','https://getapib.org:444/image/a','https://user@getapib.org/image/a']:
   self.assertFalse(server.safe_image_url(u))
  self.assertTrue(server.safe_image_url('https://getapib.org/image/a.jpg'))
 def test_provider_error_is_redacted(self):
  t=self.task()
  with patch.object(server.urllib.request,'urlopen',return_value=Stream([{'event':'error','message':'secret-value'}])):server.run(t)
  self.assertNotIn('secret-value',json.dumps(server.get_task(t['id'])))
 def test_invalid_inputs_and_secret_rejected(self):
  for v in [None,{}, {'product_name':'ok','product_facts':'sk-'+'a'*30,'design_request':'ok'}]:
   with self.assertRaises(ValueError):server.validate_inputs(v)
if __name__=='__main__':unittest.main()
