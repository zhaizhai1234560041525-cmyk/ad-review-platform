"""Local-only Dify gateway. No provider credentials are sent to the browser."""
import ssl,base64
from uploads import validate_upload
import concurrent.futures, datetime, http.server, json, mimetypes, os, re, sqlite3, threading, time, urllib.request, urllib.error, urllib.parse, uuid
from pathlib import Path
from contextlib import contextmanager
from workflow import parse_sse, normalize_result, safe_report, stage_for
ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'; DATA.mkdir(mode=0o700,exist_ok=True)
DB=DATA/'tasks.sqlite3'
LOCK=threading.RLock()
POOL=concurrent.futures.ThreadPoolExecutor(max_workers=2)
PORT=int(os.environ.get('PORT','8790'))
ORIGIN=f'http://127.0.0.1:{PORT}'
CONFIG=ROOT/'.env'

def settings():
    env={}
    if CONFIG.exists():
        for line in CONFIG.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k,v=line.split('=',1);env[k.strip()]=v.strip()
    return os.environ.get('DIFY_API_BASE',env.get('DIFY_API_BASE','http://127.0.0.1:8080/v1')).rstrip('/'),os.environ.get('DIFY_API_KEY',env.get('DIFY_API_KEY',''))

@contextmanager
def database():
    c=sqlite3.connect(DB)
    try:
        with c: yield c
    finally: c.close()

def init_db():
    with database() as c:
        c.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, request_key TEXT UNIQUE, created REAL, body TEXT)')
        rows=c.execute('SELECT id, body FROM tasks').fetchall()
        for ident,body in rows:
            t=json.loads(body)
            if t['status'] in ('queued','running'):
                t.update(status='interrupted',stage='本地服务曾重启，请核对 Dify 运行记录后重新提交',error='任务连接已中断，不会自动重复请求。')
                c.execute('UPDATE tasks SET body=? WHERE id=?',(json.dumps(t,ensure_ascii=False),ident))

def save(t):
    with LOCK,database() as c:c.execute('UPDATE tasks SET body=? WHERE id=?',(json.dumps(t,ensure_ascii=False),t['id']))
def get_task(ident):
    with database() as c:r=c.execute('SELECT body FROM tasks WHERE id=?',(ident,)).fetchone()
    return json.loads(r[0]) if r else None

def event(t,label,status='running'):
    if t['events'] and t['events'][-1]['label']==label:return
    t['events'].append({'label':label,'time':time.time(),'status':status});t['stage']=label;save(t)

def safe_image_url(url):
    u=urllib.parse.urlsplit(url)
    return u.scheme=='https' and u.hostname in {'getapib.org'} and u.port in (None,443) and not u.username and not u.password and u.path.startswith('/image/')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise ValueError('图像源重定向，停止归档')

def archive_image(t,i,url):
    dest=DATA/t['id'];dest.mkdir(exist_ok=True)
    if not safe_image_url(url):raise ValueError('图像地址不在允许的来源中')
    context=ssl.create_default_context(cafile='/etc/ssl/cert.pem') if Path('/etc/ssl/cert.pem').exists() else ssl.create_default_context()
    with urllib.request.build_opener(NoRedirect,urllib.request.HTTPSHandler(context=context)).open(urllib.request.Request(url,headers={'User-Agent':'AdReviewLocal/1.0'}),timeout=60) as r:
        b=r.read(20*1024*1024+1)
        if len(b)>20*1024*1024:raise ValueError('图片超过20MB')
        if b.startswith(b'\xff\xd8\xff'):ext='jpg'
        elif b.startswith(b'\x89PNG\r\n\x1a\n'):ext='png'
        elif b[:4]==b'RIFF' and b[8:12]==b'WEBP':ext='webp'
        else:raise ValueError('返回内容不是支持的图片')
    file=f'round-{i}.{ext}';(dest/file).write_bytes(b)
    return f'/api/tasks/{t["id"]}/image/{i}'

def ensure_round(t,i):
    existing=next((r for r in t['rounds'] if r['index']==i),None)
    if existing:return existing
    r={'index':i,'label':'初稿' if i==0 else f'第{i}次修改','image':None,'report':None}
    t['rounds'].append(r);return r

def run(t):
    try:
        base,key=settings()
        if not key:raise ValueError('尚未配置 Dify 应用 API 密钥')
        t['status']='running';event(t,'已连接审核工作流')
        workflow_inputs=dict(t['inputs']);workflow_inputs['mode']=t.get('mode','generate')
        if t.get('mode')=='upload':
            original=DATA/t['id']/t['upload_file']
            workflow_inputs['poster_data_url']='data:'+t['upload_mime']+';base64,'+base64.b64encode(original.read_bytes()).decode()
        req=urllib.request.Request(base+'/workflows/run',data=json.dumps({'inputs':workflow_inputs,'response_mode':'streaming','user':'local-platform'}).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        finished=False;started=time.monotonic()
        with urllib.request.urlopen(req,timeout=180) as response:
            for e in parse_sse(response):
                if time.monotonic()-started>1800:raise ValueError('任务超过30分钟，请到Dify核对运行状态')
                d=e.get('data') or {};typ=e.get('event');n=d.get('node_id','')
                if typ=='workflow_started':t['workflow_run_id']=e.get('workflow_run_id') or d.get('id');save(t)
                elif typ=='node_started':event(t,stage_for(n))
                elif typ=='node_finished' and d.get('status')=='succeeded':
                    out=d.get('outputs') or {}
                    m=re.fullmatch(r'r([0-2])(parse|poll|gate)',n)
                    if n=='upload_gate':
                        r=ensure_round(t,0);r['report']=safe_report(out.get('report'));save(t)
                    if m:
                        i=int(m[1]);r=ensure_round(t,i)
                        if m[2] in ('parse','poll') and out.get('image_url') and not r['image']:
                            try:r['image']=archive_image(t,i,out['image_url'])
                            except Exception:r['image_error']='预览暂未保存，最终通过版将再次尝试归档'
                        if m[2]=='gate':
                            r['report']=safe_report(out.get('report'))
                            event(t,r['label']+({'PASS':'：未发现风险','REVISE':'：发现风险，进入修改','HUMAN':'：需要人工处理'}[r['report']['decision']]))
                        save(t)
                elif typ=='workflow_finished':
                    finished=True
                    if d.get('status')!='succeeded':
                        # Do not expose raw model/HTTP errors, which can contain credentials.
                        raise ValueError('Dify 工作流未成功完成，请在 Dify 日志中检查失败节点')
                    result=normalize_result(d.get('outputs') or {})
                    i=result['round'];r=ensure_round(t,i);r['report']=result['report']
                    # Preserve earlier reports even if node events were not delivered.
                    for k,v in (d.get('outputs') or {}).items():
                        m=re.search(r'previous_review_([0-2])$',k)
                        if m:ensure_round(t,int(m[1]))['report']=safe_report(v)
                    if result['status']=='passed':
                        if t.get('mode')=='upload':
                            if not result.get('uploaded') or not (DATA/t['id']/t['upload_file']).exists():raise ValueError('上传原图与审核结果不匹配')
                        else:
                            if result.get('uploaded'):raise ValueError('审核模式不匹配')
                            r['image']=archive_image(t,i,result['poster_url'])
                        r.pop('image_error',None)
                        t['final_round']=i;t['status']='passed';event(t,'审核通过，海报已归档','success')
                    else:t['status']='blocked';event(t,'发现风险，请按建议修改后重新上传' if t.get('mode')=='upload' and result['report']['decision']=='REVISE' else '需要人工处理，已停止导出','warning')
                    t['finished_at']=time.time();save(t)
                    break
                elif typ=='error':raise ValueError('Dify 返回执行错误，请检查模型服务及运行日志')
        if not finished:raise ValueError('工作流连接提前结束，未收到最终结果，已停止导出')
    except Exception as ex:
        msg=str(ex) if isinstance(ex,ValueError) else ('Dify API 认证或服务请求失败，请检查配置' if isinstance(ex,urllib.error.HTTPError) else '服务连接或图片归档失败，可在核对 Dify 后重新提交')
        t.update(status='failed',error=msg,finished_at=time.time());event(t,msg,'error');save(t)

def validate_inputs(x):
    fields=('product_name','product_facts','design_request')
    if not isinstance(x,dict):raise ValueError('请填写海报需求')
    out={}
    for k in fields:
        v=x.get(k)
        if not isinstance(v,str) or not v.strip():raise ValueError('产品名称、产品事实和设计要求均为必填项')
        if len(v)>5000:raise ValueError('每项内容不能超过5000字')
        if re.search(r'(?:sk-|app-)[A-Za-z0-9_-]{20,}',v):raise ValueError('内容疑似包含密钥，请删除后提交')
        out[k]=v.strip()
    return out

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,code,data,ctype='application/json; charset=utf-8',headers=None):
        b=json.dumps(data,ensure_ascii=False).encode() if isinstance(data,(dict,list)) else data
        self.send_response(code);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(b)))
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Cache-Control','no-store');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'")
        for k,v in (headers or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(b)
    def valid_host(self):return self.headers.get('Host') in {f'127.0.0.1:{PORT}',f'localhost:{PORT}'}
    def do_GET(self):
        if not self.valid_host():return self.send(403,{'error':'拒绝非本机访问'})
        path=urllib.parse.urlsplit(self.path).path
        if path=='/api/health':
            base,key=settings();return self.send(200,{'configured':bool(key),'workflow':'广告海报审核闭环','local_only':True})
        if path=='/api/tasks':
            with database() as c:tasks=[json.loads(x[0]) for x in c.execute('SELECT body FROM tasks ORDER BY created DESC LIMIT 200')]
            return self.send(200,tasks)
        m=re.fullmatch(r'/api/tasks/([a-f0-9]{32})(?:/(report|download|image)(?:/([0-2]))?)?',path)
        if m:
            t=get_task(m[1])
            if not t:return self.send(404,{'error':'任务不存在'})
            mode=m[2]
            if mode is None:return self.send(200,t)
            if mode=='report':
                lines=[f'# {t["inputs"]["product_name"]} 广宣审核报告',f'任务：{t["id"]}',f'Dify运行：{t.get("workflow_run_id","未启动")}',f'状态：{t["stage"]}','审核依据：用户提供的《中华人民共和国广告法》','']
                for r in t['rounds']:lines.extend([f'## {r["label"]}',json.dumps(r['report'],ensure_ascii=False,indent=2),''])
                lines+=['说明：自动审核结果基于已提供法规和事实，不构成法律保证。']
                return self.send(200,'\n'.join(lines).encode(),'text/markdown; charset=utf-8',{'Content-Disposition':'attachment; filename="audit-report.md"'})
            if mode=='download':
                if t['status']!='passed':return self.send(403,{'error':'仅通过审核并归档成功的海报可导出'})
                i=t['final_round']
            else:
                if m[3] is None:return self.send(404,{'error':'图片不存在'})
                i=int(m[3])
            files=list((DATA/t['id']).glob(f'round-{i}.*'))
            if not files:return self.send(404,{'error':'图片尚未生成或归档失败'})
            f=files[0]
            return self.send(200,f.read_bytes(),mimetypes.guess_type(f.name)[0] or 'application/octet-stream',{'Content-Disposition':f'attachment; filename="approved-poster{f.suffix}"'} if mode=='download' else {})
        files={'/':'index.html','/upload.js':'upload.js','/app.js':'app.js','/style.css':'style.css','/favicon.svg':'favicon.svg'}
        if path in files:
            f=ROOT/'dist'/files[path];return self.send(200,f.read_bytes(),mimetypes.guess_type(f.name)[0] or 'text/plain')
        return self.send(404,{'error':'页面不存在'})
    def do_POST(self):
        if not self.valid_host() or self.headers.get('Origin') not in (None,ORIGIN,f'http://localhost:{PORT}'):
            return self.send(403,{'error':'仅允许本机同源请求'})
        if self.path!='/api/tasks':return self.send(404,{'error':'接口不存在'})
        if not self.headers.get('Content-Type','').startswith('application/json'):return self.send(415,{'error':'需要JSON请求'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<=0 or length>7*1024*1024:raise ValueError('请求过大或为空')
            req=json.loads(self.rfile.read(length));mode=req.get('mode','generate')
            if mode not in ('generate','upload'):raise ValueError('任务模式无效')
            raw_inputs=req.get('inputs')
            if mode=='upload' and isinstance(raw_inputs,dict):
                raw_inputs={**raw_inputs,'product_name':raw_inputs.get('product_name') or '上传海报','product_facts':raw_inputs.get('product_facts') or '未提供产品事实及资质依据，不能推定相关宣传已获证明。','design_request':raw_inputs.get('design_request') or '仅审核上传海报，不生成或修改图片。'}
            inputs=validate_inputs(raw_inputs)
            uploaded=validate_upload(req.get('poster_data_url')) if mode=='upload' else None
            key=req.get('request_key','')
            if not re.fullmatch('[A-Za-z0-9-]{16,64}',key):raise ValueError('请求编号无效，请刷新页面')
            with LOCK,database() as c:
                old=c.execute('SELECT body FROM tasks WHERE request_key=?',(key,)).fetchone()
                if old:
                    previous=json.loads(old[0])
                    if previous['inputs']!=inputs or previous.get('mode','generate')!=mode or previous.get('upload_sha256')!=(uploaded['sha256'] if uploaded else None):return self.send(409,{'error':'上一次提交可能已成功。请先查看任务记录，再发起不同需求。'})
                    return self.send(200,previous)
                if not settings()[1]:return self.send(503,{'error':'尚未配置Dify应用API密钥，请先完成本地接入'})
                bodies=c.execute('SELECT body FROM tasks ORDER BY created DESC LIMIT 200').fetchall()
                if sum(json.loads(x[0])['status'] in ('queued','running') for x in bodies)>=2:return self.send(429,{'error':'已有两个任务正在处理，请稍后提交'})
                t={'id':uuid.uuid4().hex,'request_key':key,'mode':mode,'created_at':time.time(),'inputs':inputs,'status':'queued','stage':'等待工作流开始','events':[],'rounds':[],'workflow_run_id':None}
                if uploaded:
                    dest=DATA/t['id'];dest.mkdir(mode=0o700,exist_ok=True)
                    filename='round-0.'+uploaded['extension'];(dest/filename).write_bytes(uploaded['bytes'])
                    t.update(upload_file=filename,upload_mime=uploaded['mime'],upload_sha256=uploaded['sha256'])
                    r=ensure_round(t,0);r.update(label='上传原图',image=f'/api/tasks/{t["id"]}/image/0')
                c.execute('INSERT INTO tasks VALUES (?,?,?,?)',(t['id'],key,t['created_at'],json.dumps(t,ensure_ascii=False)))
            POOL.submit(run,t);return self.send(202,t)
        except (ValueError,TypeError,AttributeError):return self.send(400,{'error':'输入无效：请检查必填内容，图片须为5MB以内、2000万像素以内的有效PNG/JPG/WebP静态图片'})

if __name__=='__main__':
    init_db();server=http.server.ThreadingHTTPServer(('127.0.0.1',PORT),Handler)
    print(f'广宣审核平台运行于 {ORIGIN}',flush=True)
    server.serve_forever()
