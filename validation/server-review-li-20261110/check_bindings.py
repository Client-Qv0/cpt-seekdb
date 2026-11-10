from pathlib import Path
import hashlib,json,re,subprocess
p=Path(__file__).parent; repo=p.parents[1]; official=Path('/home/li/official-git-f4d4e266-20261110')
def sha(f):return hashlib.sha256(f.read_bytes()).hexdigest()
assert sha(repo/'Dockerfile')=='6178916e2baf4b9a3b3481c1949fbbee71edca0cdae07ace94feebed19990c32'
assert sha(repo/'build-server-review/minivectordb')=='1d36080209fc61c2d4c5b65fdf2a0587048939b3c51e2eca34644bf848ec98b9'
subprocess.run(['git','-c','safe.directory='+str(repo),'-C',str(repo),'diff','--exit-code','6576b24e0774eb11352ab5bca3372cda32f8efd9','9cea05e182875ae16f3f3c9c8e9cc688a65d653c','--','src','CMakeLists.txt'],check=True)
files=[]
for entry in subprocess.check_output(['git','-c','safe.directory='+str(official),'-C',str(official),'ls-tree','-r','-z','HEAD','--','protocol_check','mysqltest','STDIO_PROTOCOL.md']).split(b'\0'):
 if not entry:continue
 meta,path=entry.split(b'\t',1);expected=meta.split()[2].decode();name=path.decode();data=(official/name).read_bytes();actual=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest();assert actual==expected,name;files.append({'path':name,'git_blob_sha1':actual,'sha256':hashlib.sha256(data).hexdigest()})
assert len(files)==49,len(files)
(p/'official-file-binding.json').write_text(json.dumps({'commit':'f4d4e26653af823a7601668802f80e374ad6643c','verified_files':files},indent=2)+'\n')
expected=json.loads((repo/'validation/docker-pin-hmy-20261110/build-comparison.json').read_text())['package_versions']
cert=[list(x) for x in re.findall(r'Unpacking (\S+) \(([^)]+)\)',(p/'docker-build.log').read_text())]
retry=[list(x) for x in re.findall(r'Unpacking (\S+) \(([^)]+)\)',(p/'docker-build-retry.log').read_text())]
actual=retry
(p/'package-comparison.json').write_text(json.dumps({'first_build_cert_records':cert,'successful_retry_unpacked_records':retry,'record_count':len(actual),'historical_record_count':len(expected),'versions_identical_to_handoff':sorted(actual)==sorted(expected)},indent=2)+'\n')
print('Official',len(files),'files byte-verified; package versions identical:',sorted(actual)==sorted(expected),'records',len(actual))
