"""Local end-to-end JSONL comparison; not the official performance driver.
Independent NumPy truth is computed before measured containers exist.
Timers consume complete output lines; JSON validation and evidence writes follow.
"""
import argparse,gzip,hashlib,json,math,os,pathlib,random,selectors,statistics,subprocess,time,uuid
import numpy as np
ROOT=pathlib.Path('/mnt/f/OceanBase/seekdb/minivectordb-hmy-c14-20261111/validation/c22-hmy-20261111/overflow')
ENV=dict(os.environ)
CPUSET=','.join(map(str,sorted(os.sched_getaffinity(0))[:2]))
def dump(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def docker(*args):return subprocess.run(['docker',*map(str,args)],env=ENV,capture_output=True,check=True,timeout=90)
def prepare(seed,rows,dim,count):
    folder=ROOT/'results'/f'workload-{seed}-{rows}-{dim}-{count}'
    if folder.exists():
        identity=json.loads((folder/'identity.json').read_text())
        assert sha(folder/'workload.json.gz')==identity['sha256'],'cached fixture hash changed'
        with gzip.open(folder/'workload.json.gz','rt') as f:return json.load(f)
    folder.mkdir()
    rng=random.Random(seed); vectors=np.array([[round(rng.uniform(-1,1),6) for _ in range(dim)] for _ in range(rows)],dtype=np.float32)
    # SQL round-trips FP32 exactly; oracle quantization matches stored precision.
    def vec(v):return '['+','.join(repr(float(x)) for x in v)+']'
    batches=[]
    for start in range(0,rows,100):
        batches.append('INSERT INTO bench VALUES '+','.join(f"({i},'g{i%5}','{vec(vectors[i])}')" for i in range(start,min(start+100,rows)))+';')
    queries=[]; truth=[]
    vd=vectors.astype(np.float64); ids=np.arange(rows)
    for i in range(count):
        q=np.array([round(rng.uniform(-1,1),6) for _ in range(dim)],dtype=np.float32)
        group=i%5 if i%2 else None
        where=f" WHERE grp='g{group}'" if group is not None else ''
        queries.append(f"SELECT id,L2_DISTANCE(v,'{vec(q)}') AS d FROM bench{where} ORDER BY d LIMIT 10;")
        eligible=ids if group is None else ids[ids%5==group]
        diff=vd[eligible]-q.astype(np.float64)
        ds=np.sqrt(np.sum(diff*diff,axis=1,dtype=np.float64))
        selected=np.lexsort((eligible,ds))[:10]
        truth.append({'group':group,'rows':[[int(eligible[j]),float(ds[j])] for j in selected]})
    result={'seed':seed,'rows':rows,'dim':dim,'count':count,'batch':100,'create':f'CREATE TABLE bench (id BIGINT PRIMARY KEY, grp VARCHAR(8), v VECTOR({dim}));','batches':batches,'queries':queries,'truth':truth,'oracle':'exhaustive numpy float64 distance over independent FP32 values, ties pk asc; outside timers and cgroup'}
    with gzip.open(folder/'workload.json.gz','wt') as f:json.dump(result,f,allow_nan=False)
    dump(folder/'identity.json',{'sha256':sha(folder/'workload.json.gz'),'numpy':np.__version__,'seed':seed,'rows':rows,'dim':dim,'queries':count,'batch':100})
    return result
class Session:
    def __init__(self,image,out,data):
        self.out=out;out.mkdir(parents=True);self.data=data;data.mkdir(parents=True,exist_ok=True)
        self.name='mvdb-perf-'+uuid.uuid4().hex[:12];self.rows=[];self.requests=[];self.snapshots=[]
        self.command=['docker','run','--name',self.name,'-i','--network','none','--read-only','--memory','128m','--memory-swap','128m','--cpus','2','--cpuset-cpus',CPUSET,'--pids-limit','128','--tmpfs','/tmp:rw,size=64m','--mount',f'type=bind,src={data},dst=/data',image]
        self.err=(out/'stderr.log').open('wb');t=time.perf_counter()
        self.p=subprocess.Popen(self.command,env=ENV,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.err,bufsize=0)
        self.buf=b'';self.sel=selectors.DefaultSelector();self.sel.register(self.p.stdout,selectors.EVENT_READ)
        try:
            raw=self.readline();self.startup=time.perf_counter()-t;assert json.loads(raw)=={'type':'ready'},raw
            self.rows.append(raw.decode());info=json.loads(docker('inspect',self.name).stdout)[0];self.info=info
            pid=info['State']['Pid'];self.pid=pid
            line=pathlib.Path(f'/proc/{pid}/cgroup').read_text().strip().splitlines()
            self.cg=pathlib.Path('/sys/fs/cgroup')/next(x[3:] for x in line if x.startswith('0::')).lstrip('/')
            self.capture('ready')
            assert (self.cg/'memory.max').read_text().strip()=='134217728'
            assert (self.cg/'memory.swap.max').read_text().strip()=='0'
            assert (self.cg/'cpu.max').read_text().strip()=='200000 100000'
        except Exception:
            self.abort()
            raise
    def readline(self,timeout=60):
        end=time.monotonic()+timeout
        while b'\n' not in self.buf:
            if not self.sel.select(max(0,end-time.monotonic())):raise TimeoutError('response timed out')
            block=os.read(self.p.stdout.fileno(),65536)
            if not block:raise RuntimeError('unexpected EOF')
            self.buf+=block
        line,self.buf=self.buf.split(b'\n',1);return line+b'\n'
    def request(self,sql=None,op='execute'):
        request={'id':len(self.requests)+1,'op':op}
        if sql is not None:request.update(sql=sql,search_mode='exact')
        raw=(json.dumps(request,separators=(',',':'))+'\n').encode();self.requests.append(raw.decode())
        start=time.perf_counter();view=memoryview(raw)
        while view:
            n=self.p.stdin.write(view);view=view[n:]
        self.p.stdin.flush();response=self.readline();elapsed=time.perf_counter()-start
        self.rows.append(response.decode());parsed=json.loads(response)
        assert type(parsed['id']) is int and parsed['id']==request['id'] and parsed.get('ok') is True,parsed
        return parsed,elapsed
    def capture(self,label):
        result={'label':label,'monotonic':time.monotonic(),'cgroup':str(self.cg),'files':{}}
        for name in ['memory.current','memory.peak','memory.stat','memory.events','memory.pressure','memory.max','memory.swap.max','cpu.max','cpu.stat','io.stat','cpuset.cpus.effective']:
            p=self.cg/name
            result['files'][name]=p.read_text() if p.exists() else None
        for name in ['status','io']:
            p=pathlib.Path(f'/proc/{self.pid}/{name}');result['files']['proc_'+name]=p.read_text() if p.exists() else None
        self.snapshots.append(result)
    def close(self):
        self.capture('pre_shutdown');response,elapsed=self.request(op='shutdown');self.p.stdin.close()
        code=self.p.wait(timeout=30);trailing=self.p.stdout.read();assert code==0 and not trailing,(code,trailing)
        self.err.close();self.sel.close();self.info_after=json.loads(docker('inspect',self.name).stdout)[0]
        dump(self.out/'container.json',{'command':self.command,'before':self.info,'after':self.info_after,'startup_s':self.startup,'shutdown_s':elapsed})
        dump(self.out/'resources.json',self.snapshots)
        for name,values in [('requests',self.requests),('stdout',self.rows)]:
            with gzip.open(self.out/(name+'.jsonl.gz'),'wt') as f:f.writelines(values)
        docker('rm','-v',self.name)
    def abort(self):
        try:self.capture('failure_before_kill')
        except Exception as error:dump(self.out/'failure-capture-error.json',{'error':str(error)})
        try:docker('kill',self.name)
        except Exception:pass
        self.p.wait(timeout=30);self.err.close()
        dump(self.out/'resources.json',self.snapshots)
        dump(self.out/'failed-container.json',json.loads(docker('inspect',self.name).stdout))
        for name,values in [('requests',self.requests),('stdout',self.rows)]:
            with gzip.open(self.out/(name+'.jsonl.gz'),'wt') as f:f.writelines(values)
        docker('rm','-v',self.name)
def check(actual,truth):
    assert actual['columns']==['id','d'],actual
    rows=actual['rows'];want=truth['rows'];assert len(rows)==len(want)==10
    ids=[r[0] for r in rows];assert len(set(ids))==10
    assert all(type(i) is int for i in ids)
    assert ids==[r[0] for r in want],(ids,want)
    if truth['group'] is not None:assert all(i%5==truth['group'] for i in ids)
    maximum=0
    for (_,distance),(_,ref) in zip(rows,want):
        assert type(distance) in (int,float) and math.isfinite(distance)
        error=abs(distance-ref);maximum=max(maximum,error)
        assert error<=1e-10+1e-12*abs(ref),(distance,ref)
    return maximum
def run(image,label,w,roundname):
    out=ROOT/'results'/roundname/label;assert not out.exists()
    data=pathlib.Path('/var/tmp/mvdb-hmy-c22-parser-overflow-20261111')/(roundname+'-'+label)
    assert not data.exists()
    s=Session(image,out/'initial',data);times={};responses=[]
    try:
        s.request(w['create']);write=[]
        for batch in w['batches']:
            result,elapsed=s.request(batch);assert result['affected_rows']==100;write.append(elapsed)
        times['write_s']=sum(write);s.capture('after_write')
        result,elapsed=s.request(w['queries'][0]);times['first_query_s']=elapsed;responses.append((0,result));s.capture('first_query')
        warmup_times=[]
        for i in range(min(10,len(w['queries']))):
            result,elapsed=s.request(w['queries'][i]);responses.append((i,result));warmup_times.append(elapsed)
        times['warmup_queries_s']=sum(warmup_times)
        times['first_equality_query_s']=warmup_times[1] if len(warmup_times)>1 else 0.0
        queries=[]
        for i,sql in enumerate(w['queries']):
            result,elapsed=s.request(sql);queries.append(elapsed);responses.append((i,result))
        times['query_s']=sum(queries);times['filtered_query_s']=sum(queries[1::2]);times['unfiltered_query_s']=sum(queries[::2]);s.capture('after_queries');s.close()
    except Exception:
        s.abort();raise
    errors=[check(result,w['truth'][i]) for i,result in responses]
    s2=Session(image,out/'restart',data)
    try:
        times['restart_ready_s']=s2.startup
        result,elapsed=s2.request(w['queries'][0]);times['restart_query_s']=elapsed;check(result,w['truth'][0])
        result,_=s2.request('SELECT id,grp FROM bench ORDER BY id;')
        assert result['columns']==['id','grp'] and result['rows']==[[i,f'g{i%5}'] for i in range(w['rows'])]
        s2.capture('after_readback');s2.close()
    except Exception:s2.abort();raise
    record={'label':label,'image':image,'seed':w['seed'],'rows':w['rows'],'dim':w['dim'],'queries':w['count'],'write_batch':100,'times':times,'query_times':queries,'write_times':write,'warmup_query_times':warmup_times,'oracle_checks':len(errors)+1,'recall':1.0,'maximum_distance_error':max(errors),'id_order_types_filter_duplicates_checked':True,'limits':{'memory':134217728,'swap':0,'cpus':2,'cpuset':CPUSET},'cold_note':'first DB query on new data and empty process rowcache; OS pagecache not globally dropped','timing':'sum of write request/read complete response intervals; JSON parsing, validation, evidence serialization, resource capture outside timers; Docker startup reported separately','physical_io_note':'raw io.stat retained; cgroup pagecache charge and asynchronous writeback can affect attribution, file sizes not treated as physical IO','harness_sha256':sha(pathlib.Path(__file__))}
    fixture=ROOT/'results'/f"workload-{w['seed']}-{w['rows']}-{w['dim']}-{w['count']}"/'workload.json.gz'
    record['workload_sha256']=sha(fixture)
    record['restart_note']='restart_ready_s includes Docker create/run CLI and recovery; not isolated recovery CPU time'
    record['io_window']='resource counters cover ready to pre_shutdown; shutdown/writeback counters may be incomplete'
    dump(out/'result.json',record);print(json.dumps({'round':roundname,'label':label,'times':times,'checks':len(errors)+1}),flush=True)
    return record
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--images',nargs='+',required=True,help='label=image');p.add_argument('--seeds',nargs='+',type=int,default=[3179]);p.add_argument('--rows',type=int,default=10000);p.add_argument('--dim',type=int,default=128);p.add_argument('--queries',type=int,default=1000);p.add_argument('--prefix',required=True);a=p.parse_args()
    images=[x.split('=',1) for x in a.images]
    for i,seed in enumerate(a.seeds):
        w=prepare(seed,a.rows,a.dim,a.queries)
        for label,image in (images if i%2==0 else images[::-1]):run(image,label,w,f'{a.prefix}-{i+1}-seed{seed}')
