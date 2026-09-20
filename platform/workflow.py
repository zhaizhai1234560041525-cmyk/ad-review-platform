"""Translate the published Dify workflow into a stable, fail-closed product contract."""
import json

def parse_sse(lines):
    parts=[]
    for raw in lines:
        line=raw.decode('utf-8') if isinstance(raw,bytes) else raw
        line=line.rstrip('\r\n')
        if not line:
            if parts:
                yield json.loads('\n'.join(parts)); parts=[]
        elif line.startswith('data:'): parts.append(line[5:].lstrip())
    if parts: yield json.loads('\n'.join(parts))

def safe_report(raw):
    try:
        r=json.loads(raw) if isinstance(raw,str) else dict(raw)
        if not isinstance(r,dict): raise ValueError()
        if r.get('decision') not in ('PASS','REVISE','HUMAN') or not isinstance(r.get('risks'),list) or type(r.get('needs_human')) is not bool:
            raise ValueError()
        if any(not isinstance(x,dict) for x in r['risks']): raise ValueError()
        if r['needs_human']: r['decision']='HUMAN'
        elif r['risks'] and r['decision']=='PASS': r['decision']='REVISE'
        return r
    except (ValueError,TypeError):
        return {'decision':'HUMAN','needs_human':True,'risks':[],'summary':'审核结果缺失或格式异常，需要人工核实。'}

def normalize_result(outputs):
    if "upload_status" in outputs:
        report=safe_report(outputs.get("upload_audit_report"))
        passed=outputs["upload_status"]=="PASS" and report["decision"]=="PASS"
        return {"status":"passed" if passed else "blocked","round":0,"report":report,"poster_url":"","uploaded":True}
    for i in range(2,-1,-1):
        for suffix in ('end','blocked'):
            p=f'r{i}{suffix}_'
            if p+'status' not in outputs: continue
            report=safe_report(outputs.get(p+'audit_report'))
            url=outputs.get(p+'poster_url','')
            passed=suffix=='end' and outputs[p+'status']=='PASS' and report['decision']=='PASS' and bool(url)
            return {'status':'passed' if passed else 'blocked','round':i,'report':report,'poster_url':url if passed else ''}
    return {'status':'blocked','round':0,'report':safe_report(None),'poster_url':''}

def stage_for(node):
    if node.startswith('upload_'):return '正在依据法规审核' if any(x in node for x in ('review','gate','end')) else '正在识别上传海报的文字与画面'
    if node=='gen':return '正在整理海报方案'
    if 'revise' in node:return '发现风险，正在修改方案'
    if any(x in node for x in ('review','gate','branch')):return '正在依据法规审核'
    if any(x in node for x in ('vision','observed')):return '正在识别海报文字与画面'
    if any(x in node for x in ('download','end')):return '正在准备审核通过的文件'
    if node.startswith(('r0','r1','r2')):return '正在生成'+('海报初稿' if node.startswith('r0') else f'第{node[1]}次修改版')
    return '任务已进入工作流'
