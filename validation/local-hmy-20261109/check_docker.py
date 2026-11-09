"""Check this WSL's Docker PID/cgroup view without touching other containers."""
import json
from pathlib import Path
import subprocess
import uuid

name = 'mvdb-cgroup-check-' + uuid.uuid4().hex
result = {'name': name, 'image': 'busybox:latest', 'network': 'none'}
try:
    create = subprocess.run(['docker', 'run', '-d', '--name', name, '--network', 'none',
                             '--memory', '128m', '--memory-swap', '128m', '--cpus', '2',
                             'busybox:latest', 'sleep', '30'], text=True, capture_output=True, check=True)
    result['container_id'] = create.stdout.strip()
    info = json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]
    result['image_id'] = info['Image']
    result['pid'] = pid = info['State']['Pid']
    result['proc_cgroup'] = Path(f'/proc/{pid}/cgroup').read_text().strip()
    relative = result['proc_cgroup'].split(':', 2)[2]
    cg = Path('/sys/fs/cgroup') / relative.lstrip('/')
    result['cgroup_path'] = str(cg)
    for field in ('memory.max', 'memory.swap.max', 'memory.peak', 'cpu.max', 'cpuset.cpus.effective', 'io.stat'):
        result[field] = (cg / field).read_text().strip()
    result['validated_limits'] = (result['memory.max'] == '134217728' and result['memory.swap.max'] == '0'
                                  and result['cpu.max'] == '200000 100000')
except Exception as error:
    result['error'] = repr(error)
finally:
    cleanup = subprocess.run(['docker', 'rm', '-f', name], text=True, capture_output=True)
    result['cleanup_returncode'] = cleanup.returncode
print(json.dumps(result, indent=2))
