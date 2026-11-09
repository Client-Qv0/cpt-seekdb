#!/usr/bin/env python3
"""Calibrate cgroup accounting for one task-owned ext4 file, no cache drops."""
import json
import os
from pathlib import Path
import subprocess
import uuid

directory = Path('/var/tmp') / ('mvdb-io-check-' + uuid.uuid4().hex)
directory.mkdir(mode=0o777)
directory.chmod(0o777)
device = f'{os.major(directory.stat().st_dev)}:{os.minor(directory.stat().st_dev)}'
name = 'mvdb-io-check-' + uuid.uuid4().hex
command = ['docker', 'run', '--name', name, '-i', '--network', 'none', '--cpus', '2',
           '--memory', '128m', '--memory-swap', '128m', '--mount', f'type=bind,src={directory},dst=/data',
           'busybox:latest', 'sh', '-c',
           'echo READY; read x; dd if=/dev/zero of=/data/calibration bs=1M count=16 conv=fsync 2>/dev/null && echo DONE; read x']
result = {'command': command, 'directory': str(directory), 'device': device}
proc = None
try:
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == 'READY'
    info = json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]
    pid = info['State']['Pid']
    cgroup = Path('/sys/fs/cgroup') / Path(f'/proc/{pid}/cgroup').read_text().strip().split(':', 2)[2].lstrip('/')
    result.update({'pid': pid, 'cgroup': str(cgroup), 'image_id': info['Image'],
                   'before': (cgroup / 'io.stat').read_text(),
                   'memory_max': (cgroup / 'memory.max').read_text(),
                   'memory_swap_max': (cgroup / 'memory.swap.max').read_text()})
    proc.stdin.write('\n'); proc.stdin.flush()
    reply = proc.stdout.readline().strip()
    result['reply'] = reply
    if reply != 'DONE':
        raise RuntimeError('container calibration write failed')
    result['after'] = (cgroup / 'io.stat').read_text()
    def counters(text):
        for line in text.splitlines():
            parts = line.split()
            if parts[0] == device:
                return {key: int(value) for key, value in (field.split('=', 1) for field in parts[1:])}
        return {}
    before, after = counters(result['before']), counters(result['after'])
    result['device_delta'] = {key: after.get(key, 0) - before.get(key, 0) for key in ('rbytes', 'wbytes')}
    result['calibration_write_bytes'] = 16 * 1024 * 1024
    result['observed_writeback'] = result['device_delta']['wbytes'] >= result['calibration_write_bytes']
    proc.stdin.write('\n'); proc.stdin.flush()
    result['exit_code'] = proc.wait(timeout=15)
except Exception as error:
    result['error'] = repr(error)
finally:
    cleanup = subprocess.run(['docker', 'rm', '-f', name], capture_output=True, text=True)
    result['cleanup_returncode'] = cleanup.returncode
    if proc and proc.poll() is None:
        proc.kill(); proc.wait()
print(json.dumps(result, indent=2))
if result.get('exit_code') != 0 or not result.get('observed_writeback'):
    raise SystemExit(1)
