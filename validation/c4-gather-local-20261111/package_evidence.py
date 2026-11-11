import pathlib,json,hashlib,difflib,shutil,datetime
R=pathlib.Path(__file__).resolve().parent;P=R/'evidence-package';P.mkdir()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def put(path,text):
 p=R/path;p.parent.mkdir(exist_ok=True,parents=True);p.write_bytes(text.encode('utf8'))
def copy(path,dest=None):
 out=P/(dest or path);out.parent.mkdir(exist_ok=True,parents=True);shutil.copyfile(R/path,out)
base=json.loads((R/'inputs/source-manifest.json').read_text())
for f in base['files']:assert sha(R/'baseline'/f['path'])==f['sha256'],f['path']
candidate=json.loads((R/'candidate-manifest.json').read_text())
for f in candidate:assert sha(R/'candidate'/f['path'])==f['sha256'],f['path']
changed=[f['path'] for f in candidate if (R/'baseline'/f['path']).read_bytes()!=(R/'candidate'/f['path']).read_bytes()]
assert set(changed)=={'src/exact_cache.hpp','tests/test_exact_cache.cpp'}
patch=''.join(''.join(difflib.unified_diff((R/'baseline'/p).read_text().splitlines(True),(R/'candidate'/p).read_text().splitlines(True),fromfile='a/'+p,tofile='b/'+p)) for p in changed)
put('candidate.patch',patch)
S={x:json.loads((R/(x+'-summary.json')).read_text()) for x in ['main','holdout','overflow']}
AA=json.loads((R/'aa1-summary.json').read_text());RES=json.loads((R/'resources-summary.json').read_text())
BIN=json.loads((R/'runtime/candidate-binary.json').read_text())
assert (R/'PERFORMANCE_STOP.json').is_file()
assert not (R/'full-regression').exists()
lines=['C4 gather replacement: rejected performance candidate','',
'Outcome: keep frozen production 87c2778ed0688e6e56152baf02bc4f4355667458. No production/Agent/shared-branch change; no formal submission.',
'The isolated candidate passed main/holdout query gates but failed the predeclared overflow <=5% regression limit. No retry or selection of fastest rounds.',
'Evidence commit adds only validation/c4-gather-local-20261111. Candidate patch is archived there as a rejected experiment; it is not installed under repository src/.','',
'Version binding',
'Baseline commit: 87c2778ed0688e6e56152baf02bc4f4355667458.',
'Baseline binary SHA256: b2501504b9e0b13afe6dc35c4e24bf65efaf4351e98ae3d94fc6327f1bd9ee67.',
'Baseline local image: sha256:4dcb69128fbea4448e1dc4b0b37c5412ce788290a4fa410b1d976c1fc002de74.',
'Candidate source: frozen baseline plus candidate.patch; full file hashes in candidate-manifest.json. Not represented as the baseline commit itself.',
'Candidate binary SHA256: '+BIN['sha256']+'.',
'Candidate local image: '+BIN['image']+'.',
'Candidate manifest SHA256: '+sha(R/'candidate-manifest.json')+'.',
'Frozen bench.py SHA256: 2bf78d1307197b23f08e02f842594e0d8c271b706cd9ac8c303673db0b5bf5ed.',
'Supplemental default-JSONL SQL oracle SHA256: '+sha(R/'tests/sql_lane_edges.py')+'.',
'All 88 baseline selected files and every candidate manifest file rechecked byte-for-byte before packaging. Full source/build and tool hashes accompany this report.','',
'Diagnosis and single change',
'Whole-phase microbench compared original AVX2 gather and four independent FP32 loads. Stride5/random batches were about 60.52%/62.28% faster in the microbench; aligned blocks were 1.55% slower at median. This was only a reason to try the patch, not SQL performance evidence.',
'The patch uses each selected row index plus d*4, assembles four scalar loads with _mm_setr_ps, preserves contiguous _mm_loadu_ps, ordered per-dimension doubles, separate multiply/add, sqrt, PK ties, scalar fallback and the 12MiB view budget. No cache structure/layout/budget, filter index, parser, storage, WAL or ANN change.',
'The real candidate ELF contains/calls the AVX2 kernel, has no gather or FMA there and retains vmulpd/vaddpd/vsqrtpd. CPU probe reports exact::available=1. Assembly and actual binary hashes are retained.','',
'Method',
'Local Windows-host WSL2 Ubuntu24.04 only; no teammate/server measurement claimed. Same pinned Docker Release, default formal JSONL, read-only root, separate ext4 /data, no network, 2 CPU on CPUs0,1, cgroup128MiB and zero swap.',
'Main: six alternating A/B pairs, 10000x128, 1000 Top10 queries, seeds3179/3181/3187 repeated. Holdout: three first-used seeds66007/66029/66041, same workload. Overflow: three pairs32000x128,100 queries,seeds3179/3181/3187.100-row write batches.',
'All outputs consumed; independent FP32-input exhaustive distance/filter/ordered TopK/duplicate-ID/Recall reference prepared outside timing and cgroup. First query/cache build, ten warmups, measured warm queries, and process restart are separated. Host/device caches were not globally flushed.',
f'A/A: 6 pairs, median abs(B/A-1)={AA["median"]*100:.6f}%, max={AA["max"]*100:.6f}%; pass. One run only.','',
'Paired change table. Positive is elapsed-time REDUCTION (faster); negative is regression. Medians are of paired ratios, not ratios of unpaired medians.',
'phase | query | filtered | unfiltered | write | first cold query | restart ready | restart query']
for phase in S:
 m=S[phase]['metrics'];keys=['query_s','filtered_query_s','unfiltered_query_s','write_s','first_query_s','restart_ready_s','restart_query_s']
 lines.append(phase+' | '+' | '.join(f'{m[k]["median"]*100:+.4f}%' for k in keys))
lines+=['','Per-round total query reduction:']
for phase in S:lines.append(phase+': '+', '.join(f'{x*100:+.6f}%' for x in S[phase]['metrics']['query_s']['reductions']))
lines+=['','All seven time metrics per round are preserved in each runner.stdout.log and result.json; summary JSON includes min/max/wins.',
'Rejection: overflow total query median -5.470589% (0/3 wins) exceeds allowed regression; filtered median -6.804667%, unfiltered -3.930522%. Main and holdout cold-first median regressions of5.777918%/5.704695% are separately disclosed. The overflow data alone requires rejection.',
'The32000x128 FP32 vectors alone exceed12MiB, so this workload uses the budget-bypass path. The changed noncontiguous kernel is not a demonstrated cause of the overflow regression. Binary layout, execution-state and other effects have NOT been isolated; no causal claim or new candidate is made.','',
'Resources (actual cgroup memory.peak maximum across initial/restart stages; not process RSS)',
'phase/label | max memory.peak bytes | max sampled anon bytes | max sampled file bytes | pgscan | OOM']
for x in RES['summary']:
 if x['phase']=='aa1':continue
 lines.append(f'{x["phase"]}/{x["label"]} | {x["peak_max_bytes"]} | {x["anon_max_sample_bytes"]} | {x["file_max_sample_bytes"]} | {x["pgscan_max"]} | {x["oom"]}')
lines+=['Anonymous/file maxima are sampled separately and need not coincide with memory.peak. memory.events, memory.pressure, memory.stat, CPU counters and raw io.stat are retained per stage. No new resident cache data structure was introduced. The bounded 10k/32k vector tests do not establish a high-cardinality short-record maximum or eliminate O(N) primary-key growth.',
'Raw cgroup/device and process IO counters are preserved. Shared WSL device/writeback attribution is not calibrated; file lengths are not physical IO, and no official score is derived.','',
'Correctness evidence actually executed',
'Release CTest7/7 passed including arbitrary lanes, adjacent block crossing, repeated/random lanes, tails and non-multiple dimensions with bitwise scalar agreement.',
'858-statement baseline/candidate distance differential passed against independent FP32 scalar reference; this existing test uses explicit development protocol and is not formal protocol proof.',
'Supplemental default formal JSONL:6120 queries and24080 bitwise distance checks per version; BIGINT primary keys above2^53, BIGINT/VARCHAR filters,0..5 eligible rows,mod5,PK ties,cold/hot lifecycle,updates,rollback/commit and clean restart all passed. VARCHAR is not treated as a supported primary key type.',
'Default JSONL regression passed on both binaries on ext4: framing/flush, Unicode and request-ID types, error continuation, >4MiB response, shutdown/EOF rollback, broken stdout and recovery. Native acceptance21 cases:20pass/1stress skip; optimization12cases:11pass/1large skip.',
f'Actual benchmark workload oracle checks: {RES["oracle_checks"]} including A/A, all Recall1, ordered IDs/types/filter/distance/duplicates checked. Excluding A/A,18888 checks.','',
'Failed test retained',
'First formal regression used /mnt/c for data and failed on the BASELINE with IO:truncate sort temporary file:No such file or directory. Minimal mkstemp/write/unlink/ftruncate reproduced errno2 there and succeeded on /var/tmp. The unchanged regression was rerun on Linux data directories and both versions passed. See checks/ and checks-ext4/filesystem-probe.json. This is a mount-compatibility observation, not a candidate-only defect or proof of general POSIX support.','',
'Not executed / not claimed',
'Following the documented performance stop gate, final retained-candidate sanitizer, official original public driver, default-Docker SIGKILL resource regression, acceptance--stress and optimization--large were NOT started. full_regression.py is a prepared but unexecuted plan, not test evidence.',
'No power-loss, hidden formal case, unsupported platform/CPU fallback or current official score guarantee. Existing CREATE INDEX/ANN implementation gaps and high-cardinality primary-key bound remain independent issues.',
'Waiting for official evaluation: hidden performance workload applicability and any change in official raw score cannot be established locally. This rejected candidate must not be submitted as an accepted improvement. No formal assessment was submitted.',
'Next useful work: isolate the repeatable overflow-path slowdown and first-cold-query cost under a separately declared diagnostic experiment, before attempting another load-kernel patch. Do not rerun this candidate until a favorable sample is found.','',
'Learning evidence: this report records Agent decisions and observed tool results only. Agent material was not rewritten, no student learning or historical feedback was invented.','']
put('C4_REPORT.txt','\n'.join(lines))
for p in ['C4_REPORT.txt','PLAN.txt','PERFORMANCE_STOP.json','candidate.patch','candidate-manifest.json','micro-summary.json','aa1-summary.json','main-summary.json','holdout-summary.json','overflow-summary.json','resources-summary.json','micro.cpp','prepare_candidate.py','diagnose_and_aa.py','build_candidate.py','run_checks.py','checks_ext4.py','run_pairs.py','full_regression.py','summarize_pairs.py','package_evidence.py','tests/sql_lane_edges.py','inputs/source-manifest.json']:
 copy(p)
for p in ['src/exact_cache.hpp','tests/test_exact_cache.cpp']:copy('candidate/'+p,'rejected-candidate/'+p)
for folder in ['runtime','checks','checks-ext4','checks-sql-lane-edges','aa1','main','holdout','overflow']:
 for p in sorted((R/folder).rglob('*')):
  if not p.is_file() or 'data' in p.parts or '__pycache__' in p.parts:continue
  if p.suffix in ['.json','.log','.py','.txt','.cpp'] and p.stat().st_size<1000000:
   copy(p.relative_to(R).as_posix())
copy('checks/actual-candidate-avx2.asm')
repro='''Reproduction of a REJECTED C4 experiment; no production change.
Use a new evidence directory, Linux x86_64 AVX2 + cgroupv2 Docker, CPU0/1 available.
Fetch frozen commit87c2778ed0688e6e56152baf02bc4f4355667458 into an isolated checkout.
Extract exactly the88 files listed in inputs/source-manifest.json into R/baseline and verify hashes.
Preserve the prior evidence; do not point output paths at the existing directories here.
Build baseline with its unchanged Dockerfile (networkhost only for package build); binary must match b2501504...ee67.
Build Docker builder target with same source; prepare an isolated NumPy venv for the frozen portable benchmark.
These scripts record this host's exact paths and Docker socket; when adapting those paths, preserve original scripts and record hashes of adapted copies. Never start a second daemon against an occupied data-root.
diagnose_and_aa.py: whole-phase microbench and six A/A pairs; prepare_candidate.py: exact isolated patch; build_candidate.py: sameRelease image and seven unit tests.
run_checks.py retains the first native formal failure on Windows /mnt/c; checks_ext4.py shows the minimal filesystem reproduction and successful unchanged tests on Linux data. For a freshLinux-only reproduction skip theWindows-specificdiagnosis but explicitly record it as not applicable.
tests/sql_lane_edges.py must use a fresh Linux output directory because it places persistent data beneath it.
run_pairs.py executes main/holdout/overflow serially and stops with code2 if a gate fails. It must not proceed to full_regression.py after a stop. Each benchmark's tool/bench.frozen.py, adaptedtool and adapter-manifest preserve the exact benchmark implementation.
The overflow regression, not a database crash, triggered this experiment's stop. No sanitizer or originalofficial public cases were run for C4 after rejection.
candidate.patch and rejected-candidate/ are experimental records only. Do not apply them to the accepted production branch.
Large raw request/stdout traces, workload arrays, executables, complete assembly and native test data are retained locally, listed by hashes inARTIFACTS.json; not all are included inGit. Repeat experiments generate new evidence.
Raw memory andIO counters are retained. No RSS substitution, file-size physicalIO estimate or officialscore prediction is made.
'''
(P/'REPRODUCE.txt').write_bytes(repro.encode())
artifacts=[]
for p in sorted(R.rglob('*')):
 if not p.is_file() or P in p.parents or '__pycache__' in p.parts or p.name in ['evidence-package-manifest.json','EVIDENCE_MANIFEST.json']:continue
 rel=p.relative_to(R).as_posix()
 artifacts.append({'path':rel,'bytes':p.stat().st_size,'sha256':sha(p),'included_in_git_evidence_package':(P/rel).exists()})
(P/'ARTIFACTS.json').write_bytes((json.dumps({'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Local R4 evidence root; large raw artifacts retained locally, not all inGit','files':artifacts},indent=2)+'\n').encode())
manifest=[{'path':p.relative_to(P).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)} for p in sorted(P.rglob('*')) if p.is_file()]
put('evidence-package-manifest.json',json.dumps(manifest,indent=2)+'\n')
print(json.dumps({'files':len(manifest),'bytes':sum(x['bytes'] for x in manifest),'raw_files':len(artifacts),'raw_bytes':sum(x['bytes'] for x in artifacts),'formal_submission':False,'candidate_retained':False}))
