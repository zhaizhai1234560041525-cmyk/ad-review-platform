import unittest, json
from workflow import parse_sse, normalize_result, safe_report

PASS={'decision':'PASS','needs_human':False,'risks':[],'summary':'未发现风险'}
class WorkflowTests(unittest.TestCase):
 def test_sse(self):
  lines=[b': ping\n',b'\n',b'data: {"event":"workflow_started"}\n',b'\n',b'data: {"event":"workflow_finished",\n',b'data: "data":{}}\n',b'\n']
  self.assertEqual([x['event'] for x in parse_sse(lines)],['workflow_started','workflow_finished'])
 def test_final_round(self):
  o={'r1end_status':'PASS','r1end_poster_url':'https://getapib.org/image/test.jpg','r1end_audit_report':json.dumps(PASS)}
  self.assertEqual(normalize_result(o)['round'],1)
  self.assertEqual(normalize_result(o)['status'],'passed')
 def test_risky_pass_blocked(self):
  self.assertEqual(safe_report({**PASS,'risks':[{'evidence':'最佳'}]})['decision'],'REVISE')
 def test_missing_bool_blocked(self):
  for v in [None,'false',0]:
   self.assertEqual(safe_report({**PASS,'needs_human':v})['decision'],'HUMAN')
 def test_missing_outputs_not_pass(self):
  self.assertEqual(normalize_result({})['status'],'blocked')
 def test_human_end(self):
  self.assertEqual(normalize_result({'r2blocked_status':'HUMAN','r2blocked_audit_report':json.dumps({**PASS,'decision':'HUMAN'})})['status'],'blocked')
 def test_malformed_report(self):
  self.assertEqual(safe_report('nonsense')['decision'],'HUMAN')
 def test_scalar_json_blocked(self):
  for value in ['null','[]','1','true']:
   self.assertEqual(safe_report(value)['decision'],'HUMAN')
 def test_invalid_risk_blocked(self):
  self.assertEqual(safe_report({**PASS,'risks':[None]})['decision'],'HUMAN')
 def test_final_requires_photo(self):
  self.assertEqual(normalize_result({'r0end_status':'PASS','r0end_audit_report':json.dumps(PASS)})['status'],'blocked')
if __name__=='__main__':unittest.main()
