"""Assemble compact truthful material and verify the evidence-only delivery."""
from pathlib import Path
import hashlib,json,statistics,subprocess
P=Path(__file__).resolve().parent;ROOT=P.parents[1]
BASE='200b7ba19d5fee4096b46e63534ab73ae35cae93'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def read(p):return json.loads(p.read_text())
def git(*a):return subprocess.check_output(['git','-C',str(ROOT),*a])
def verify():
 m=read(P/'MANIFEST.json')
 for x in m['published']:assert sha(P/x['path'])==x['sha256'],x['path']
 assert sha(ROOT/'agent/conversation.json')==m['material_sha256']
 subprocess.run(['git','-C',str(ROOT),'diff','--exit-code',BASE,'--','src','CMakeLists.txt','Dockerfile','.dockerignore','tests','validation/perf-20261110-stdio/scripts/bench.py'],check=True)
 print('Verified',len(m['published']),'published files; frozen source and material binding')
def main():
 for phase in ('cold','write'):assert (P/f'runs-{phase}'/'PASS').is_file()
 checks=0; stats={}; outliers={}
 for k in (0,5,20):
  d=P/('runs-write' if k else 'runs-cold')/str(k); summary=read(d/'summary.json')
  rows={c:[read(d/f'{c}-{i}.json') for i in range(1,7)] for c in ('aa','bc')}
  for kind,rr in rows.items():
   for i,r in enumerate(rr,1):
    for side in ('left','right'):
     run=d/f'{k}-{kind}-{i}-{side}'
     x=read(run/'result.json');assert x==r[side]
     checks+=x['oracle_checks'];assert x['oracle_checks']==100
     assert len(x['update_times'])==(99//k if k else 0)
     assert x['memory_peak']<=134217728
     assert not read(run/'container.json')['after']['State']['OOMKilled']
  for key,v in summary.items():
   if not isinstance(v,dict):continue
   def get(x):return x['prefix_s'][key] if not k else x[key]
   a=[100*(1-get(r['right'])/get(r['left'])) for r in rows['aa']]
   b=[100*(1-get(r['right'])/get(r['left'])) for r in rows['bc']]
   assert a==v['aa_pct'] and b==v['paired_reduction_pct']
   assert statistics.median(b)==v['median_pct']
   assert max(map(abs,a))==v['noise_max_abs_pct'] and sum(x>0 for x in b)==v['wins']
   assert v['stable_win']==(v['wins']>=5 and v['median_pct']>v['noise_max_abs_pct'])
   if not k:
    i=max(range(6),key=lambda i:abs(a[i]));r=rows['aa'][i]
    outliers[key]={'round':i+1,'seed':r['seed'],'left_ms':1000*get(r['left']),'right_ms':1000*get(r['right'])}
  stats[k]=summary
 assert checks==7200
 assert read(P/'runs-cold/bindings.json')==read(P/'runs-write/bindings.json')
 c=stats[0]; ns=[1,5,10,20,100]; stable=[n for n in ns if all(c[str(x)]['stable_win'] for x in ns if x>=n)]
 n=min(stable) if stable else None
 assert n==c['earliest_stable_observed']
 def fmt(k,key):
  v=stats[k][key];return f'{v["median_pct"]:+.2f}%（{v["wins"]}/6 更快，A/A 最大 {v["noise_max_abs_pct"]:.2f}%）'
 verdicts=[]
 for k in (5,20):
  v=stats[k]['total_s']
  if v['stable_win']:s='C2 在这个实测写读条件下稳定更快'
  elif v['wins']<=1 and -v['median_pct']>v['noise_max_abs_pct']:s='基线在这个实测写读条件下稳定更快'
  else:s='无法确认哪版稳定更快'
  verdicts.append(f'每 {k} 查写一次：{s}')
 decision=f"本轮最早稳定回本采样点：{n if n else '无法确认'}。"+'；'.join(verdicts)+"。保留已经验证的长读批次结论；不根据本轮未跨过校准噪声的观察设置查询次数切换规则。"
 lines=['# C2 短批次回本与写后失效复测','',
 '在当前服务器用 9cea05e 和 200b7ba 的冻结二进制，生产源码、正式协议、原 benchmark 均未修改。两阶段 bindings.json 的镜像 ID 与二进制 SHA-256 一致。','',
 '每工况六组 A/A 与六组基线/C2，种子 3179/3181/3187 各两次、顺序交替；新容器及独立数据目录，2 CPU、128 MiB、0 swap，cpuset 0,1。10,000×128，每条请求计时从写入到完整响应读取，解析和独立参考在计时外。装载及启动另列；首查无预热。写读工况含 100 次查询，交替修改 id=0 的 grp（g0/g5），每 5 或 20 查询更新一次，末尾不更新。','',
 '## 结果（正数表示 C2 更快）','',
 '| 工况 | 配对中位改善 / 胜组 / A/A 最大差 |','|---|---|']
 for z in ns:lines.append(f'| 首 {z} 次查询 | {fmt(0,str(z))} |')
 for k in (5,20):
  for key,label in [('query_s','查询'),('update_s','更新'),('total_s','合计')]:lines.append(f'| 每 {k} 查写一次 · {label} | {fmt(k,key)} |')
 lines+=['',decision,'','短批次只在某采样点及其所有后续点均达到 5/6 胜且中位改善大于该点 A/A 最大绝对差时确认回本。中位方向变化不是稳定区间，不插值。A/A 使用完全相同的二进制；其最大差限制结论，不能归因于 C2。','',
 '## A/A 最大差对应的实测值','', '| 查询数 | 轮次 / seed | 左 ms | 右 ms |','|---:|---|---:|---:|']
 for k,v in outliers.items():lines.append(f"| {k} | {v['round']} / {v['seed']} | {v['left_ms']:.3f} | {v['right_ms']:.3f} |")
 lines+=['','所有逐组原值、校准与比较方向见各工况的配对 JSON；资源快照保留 memory.peak、anon/file、事件、CPU 和 io.stat。资源计数不足以单独解释波动，不用文件大小推算物理 I/O。','',
 '## 验证与材料','',
 '72 个容器、7,200 条实测查询通过独立参考，已校验每次 UPDATE 的确认和末行状态，所有实测容器无 OOM。首次预检的文本比较错误在装载前发生，已保留，不计入任何配对。','',
 '用户在实测前回答“不确定，先测”；短批次结果后说“你做决定，在做出决定前须经过独立思考”。后者是委托，最终解释归 Agent，不能当作用户自己的技术判断。未正式提测，不预测 Agent 得分，之前没有有效原始分的原因仍未知。','',
 '复现：在新输出/数据路径使用 experiment.py cold、experiment.py write（NumPy 2.3.3、实际 Docker 宿主 cgroup）；当前脚本拒绝覆盖既有输出。大型 SQL、响应和数据库仅保留在服务器，MANIFEST 绑定本目录原始文件。']
 (P/'REPORT.md').write_text('\n'.join(lines)+'\n')
 agent=ROOT/'agent/conversation.json';old=git('show',BASE+':agent/conversation.json');assert old.startswith(b'{\n') and len(old)==122791
 entry={'source':'actual user responses, tool results, and agent decision; no inferred student explanation',
 'before':{'source':'user','content':'不确定，先测'},
 'short_batch':{'source':'tool_result_summary','content':'; '.join(f'{n}次 {fmt(0,str(n))}' for n in ns)+'；未确认稳定回本点。'},
 'after_short':{'source':'user','content':'你做决定，在做出决定前须经过独立思考'},
 'write_read':{'source':'tool_result_summary','content':'; '.join(f'每{k}查更新一次：查询 {fmt(k,"query_s")}、更新 {fmt(k,"update_s")}、合计 {fmt(k,"total_s")}' for k in (5,20))+'。7200条查询独立核验通过。'},
 'decision':{'source':'agent','content':decision},
 'scope':'无用户技术解释或复盘记录；无正式评分。上次无有效原始分的原因未确认。'}
 added=('  "cache_amortization_li_20261111": '+json.dumps(entry,ensure_ascii=False,indent=2).replace('\n','\n  ')+',\n').encode()
 new=old[:2]+added+old[2:];assert len(added)<=4096 and len(new)<=131072 and agent.read_bytes() in [old,new]
 agent.write_bytes(new)
 subprocess.run(['python3',str(ROOT/'tests/test_agent_material.py'),'-v'],stdout=(P/'agent-check.log').open('w'),stderr=subprocess.STDOUT,check=True)
 raw=[];pub=[]
 for f in sorted(P.rglob('*')):
  if not f.is_file() or f.name in ['MANIFEST.json','.gitignore'] or '__pycache__' in f.parts:continue
  item={'path':str(f.relative_to(P)),'bytes':f.stat().st_size,'sha256':sha(f)}
  (raw if f.suffix in ['.gz','.jsonl'] else pub).append(item)
 ig=P/'.gitignore';ig.write_text('*.gz\n*.jsonl\n__pycache__/\n')
 pub.append({'path':'.gitignore','bytes':ig.stat().st_size,'sha256':sha(ig)})
 (P/'MANIFEST.json').write_text(json.dumps({'base_commit':BASE,'published':pub,'retained_server_only':raw,'material_sha256':sha(agent),'material_bytes':len(new),'added_bytes':len(added)},indent=2)+'\n')
 verify();print(decision,'material bytes',len(new),'added',len(added))
if __name__=='__main__':
 import sys
 verify() if len(sys.argv)>1 and sys.argv[1]=='verify' else main()
