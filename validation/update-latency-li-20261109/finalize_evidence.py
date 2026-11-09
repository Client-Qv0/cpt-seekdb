from pathlib import Path
import json,hashlib,subprocess,statistics
p=Path(__file__).parent; repo=p.parents[1]
def sha(f):
 h=hashlib.sha256()
 with f.open('rb') as s:
  for chunk in iter(lambda:s.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
r=json.loads((p/'resource-regression/docker-resource-regression-results.json').read_text()); compat=json.loads((p/'index-compatibility.json').read_text()); summary=json.loads((p/'paired-original/summary.json').read_text()); assert r['success'] and compat['passed'] and summary['all_planned_runs_passed'] and summary['identities_unchanged']; assert (p/'pipeline.exit').read_text().strip()=='0'
assert all(not c['docker_final_state']['OOMKilled'] for c in r['containers'])
validation='''# Local validation, 2026-11-09

All rows describe executions on this server, not historical test passes.

| Configuration / test | Result | Evidence |
|---|---|---|
| V2 Release CTest | 5/5, zero failed | ctest-release.log |
| B Release CTest | 4/4, zero failed | ctest-baseline.log |
| V2 expanded Release blackbox | 19/19, zero skips | acceptance-release-full.log |
| V2 expanded Release extra regression | 11/11, zero skips | optimization-release-full.log |
| V2 ASan/UBSan CTest | 5/5, zero failed | ctest-sanitize.log |
| V2 ASan/UBSan blackbox | 18 pass; 1 storage-pressure test skipped | acceptance-sanitize.log |
| V2 ASan/UBSan extra regression | 8 pass; large-output class skipped | optimization-sanitize.log |
| Actual 128 MiB cgroup large-output/storage | 4/4, zero failures/errors/skips; no container OOM | resource-regression/ |
| B/V2 WAL/checkpoint compatibility | both directions pass; full 1000 initial/999 modified rows including vectors | index-compatibility.json |
| Original-history paired workloads | 18/18, all independent result/resource checks pass | paired-original/ |
| Separate diagnostic history replays | 6/6, all issued acknowledgement/row checks pass | diagnostic-*/run.json |
| Immutable handoff evidence | 13+49+320 files, zero mismatches after all tests | handoff-verify-after.txt |

ASan/UBSan uses Debug, -fsanitize=address,undefined -fno-omit-frame-pointer; leak detection and halt-on-error enabled. No sanitizer error was reported in executed suites. Stress/large-output success under Release/cgroup does not imply sanitizer coverage of skipped cases. Logs identify their exact scopes.

All resource tests read back memory.max=134217728, memory.swap.max=0, cpu.max=200000 100000. Their cgroup peak values are recorded below; completion does not imply ample memory headroom. io.stat is raw shared-device observation, not calibrated official physical I/O.

'''
validation+='| Resource process | memory.peak bytes | Exit code | OOMKilled |\n|---|---:|---:|---|\n'
for c in r['containers']:
 st=c['docker_final_state']; validation+=f"| {c['label']} | {c['peak_observed_bytes']} | {st['ExitCode']} | {st['OOMKilled']} |\n"
validation+='\nRequested SIGKILL in storage recovery can produce 137 without OOM. Resource driver assertion logic remains the frozen four-case harness; path, socket, runtime image and evidence metadata were adapted in resource_driver.py. The existing Docker daemon was reused and remains running.\n\nProduction candidate remains byte-identical to V2; no new source fix or official assessment is claimed.\n'
(p/'VALIDATION.md').write_text(validation)
production=json.loads((repo/'validation/cardinality-20261109/candidate-v2-production-manifest.json').read_text()); assert all(sha(repo/e['path'])==e['sha256'] for e in production['files']); (p/'production-manifest.json').write_text(json.dumps(production,indent=2)+'\n')
paths=['build-handoff/minivectordb','build-update-baseline/release/minivectordb','build-update-sanitize/minivectordb','build-handoff/minivectordb-diagnostic','build-update-baseline/release/minivectordb-diagnostic','build-handoff/checkpoint-helper','build-update-baseline/checkpoint-helper']
(p/'binary-manifest.json').write_text(json.dumps({'files':[{'path':name,'bytes':(repo/name).stat().st_size,'sha256':sha(repo/name)} for name in paths],'note':'Instrumented executables and helpers are diagnostic objects, not final production timing objects.'},indent=2)+'\n')
files=[];retained=[]
for f in sorted(p.rglob('*')):
 if not f.is_file():continue
 rel=f.relative_to(p)
 if '__pycache__' in rel.parts or rel.name=='evidence-manifest.json':continue
 item={'path':str(rel),'bytes':f.stat().st_size,'sha256':sha(f)}
 if 'data' in rel.parts or (rel.parts[0]=='official' and f.suffix in ['.json','.txt']):retained.append(item)
 else:files.append(item)
(p/'evidence-manifest.json').write_text(json.dumps({'files':files,'local_retained_not_committed':retained,'manifest_excludes_itself':True,'learning_material':{'path':'agent/conversation.json','sha256':sha(repo/'agent/conversation.json')},'official_assessment_submitted':False,'production_changed':False},indent=2)+'\n')
print('evidence',len(files),'retained local',len(retained),'resource containers',len(r['containers']))
