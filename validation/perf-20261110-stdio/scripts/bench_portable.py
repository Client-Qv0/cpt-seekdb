#!/usr/bin/env python3
"""Path/daemon adapter for the frozen 2026-11-10 local benchmark, not a scorer.

The frozen bench.py is never edited. An auditable copy with exactly three
environment/path substitutions is generated in a new output directory.
Requires Linux and the Docker daemon's host PID/cgroup namespace, not Docker
Desktop's remote VM. No relaxation or approximation of resource accounting.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

FROZEN_SHA256 = '2bf78d1307197b23f08e02f842594e0d8c271b706cd9ac8c303673db0b5bf5ed'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')


def parse():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--images', nargs='+', required=True, metavar='LABEL=IMAGE')
    p.add_argument('--output-root', required=True, type=Path, help='New absolute output directory; never overwrite evidence')
    p.add_argument('--data-root', required=True, type=Path, help='New absolute directory on the Docker host, not inside the repository')
    p.add_argument('--docker-host', help='Local Unix socket; otherwise use current Docker context/environment')
    p.add_argument('--preflight-only', action='store_true', help='Probe the host/cgroup/limits without running SQL')
    p.add_argument('--prefix', required=True)
    p.add_argument('--seeds', nargs='+', type=int, default=[3179])
    p.add_argument('--rows', type=int, default=10000)
    p.add_argument('--dim', type=int, default=128)
    p.add_argument('--queries', type=int, default=1000)
    a = p.parse_args()
    if sys.flags.optimize or not __debug__:
        p.error('Python -O/-OO/PYTHONOPTIMIZE disables the frozen correctness assertions; run without optimization')
    if sys.platform != 'linux':
        p.error('Run inside Linux/WSL2 with a local Linux Docker Engine and host cgroup access')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.prefix):
        p.error('prefix must contain only letters, digits, underscore or hyphen')
    if a.rows < 100 or a.rows % 100 or a.dim < 1 or a.queries < 1:
        p.error('rows must be a positive multiple of 100 (frozen batch assertions); dim and queries must be positive')
    labels = []
    for pair in a.images:
        if '=' not in pair:
            p.error('image arguments must be LABEL=IMAGE')
        label, image = pair.split('=', 1)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', label) or not image or image.startswith('-'):
            p.error('invalid label or image')
        labels.append(label)
    if len(labels) < 2 or len(set(labels)) != len(labels):
        p.error('provide at least two images with distinct labels for paired runs')
    for path in (a.output_root, a.data_root):
        if not path.is_absolute() or path.exists() or ',' in str(path):
            p.error('output/data paths must be absolute, new, and contain no comma')
    a.output_root = a.output_root.resolve()
    a.data_root = a.data_root.resolve()
    if a.output_root == a.data_root or a.output_root in a.data_root.parents or a.data_root in a.output_root.parents:
        p.error('output-root and data-root must be separate, non-nested directories')
    if a.docker_host and not a.docker_host.startswith('unix:///'):
        p.error('only a local Unix Docker socket is supported; remote daemon resource accounting would be invalid')
    return a


def main():
    a = parse()
    frozen = Path(__file__).resolve().with_name('bench.py')
    source = frozen.read_bytes()
    if sha(source) != FROZEN_SHA256:
        raise RuntimeError('Frozen bench.py differs from the recorded tested version; do not silently adapt a different tool')
    # Validate NumPy before producing any measurements.
    import numpy
    env = dict(os.environ)
    env.pop('PYTHONOPTIMIZE', None)
    if a.docker_host:
        env.pop('DOCKER_CONTEXT', None)
        env['DOCKER_HOST'] = a.docker_host
    a.output_root.mkdir(parents=True)
    a.data_root.mkdir(parents=True)
    (a.output_root / 'results').mkdir()
    tool = a.output_root / 'tool'
    tool.mkdir()
    (tool / 'bench.frozen.py').write_bytes(source)

    def docker(*args, check=True):
        r = subprocess.run(['docker', *map(str, args)], env=env, capture_output=True, timeout=45)
        if check and r.returncode:
            raise RuntimeError(r.stderr.decode(errors='replace'))
        return r

    # Fail closed unless the probe's PID and cgroup belong to this host.
    probe = 'mvdb-handoff-probe-' + uuid.uuid4().hex[:12]
    try:
        info = json.loads(docker('info', '--format', '{{json .}}').stdout)
        if info.get('CgroupVersion') != '2' or 'docker desktop' in info.get('OperatingSystem', '').lower():
            raise RuntimeError('Requires native local Docker Engine with cgroup v2; Docker Desktop VM accounting is not supported')
        images = {}
        for pair in a.images:
            label, image = pair.split('=', 1)
            record = json.loads(docker('image', 'inspect', image).stdout)[0]
            images[label] = {'requested': image, 'id': record['Id'], 'architecture': record.get('Architecture')}
        first_image = next(iter(images.values()))['id']
        command = ['run', '-d', '--name', probe, '--network', 'none', '--read-only',
                   '--memory', '128m', '--memory-swap', '128m', '--cpus', '2',
                   '--cpuset-cpus', '0,1', '--pids-limit', '128', '--entrypoint', '/bin/sh',
                   first_image, '-c', 'sleep 120']
        cid = docker(*command).stdout.decode().strip()
        state = json.loads(docker('inspect', probe).stdout)[0]
        pid = state['State']['Pid']
        membership = Path(f'/proc/{pid}/cgroup').read_text()
        rel = next(line[3:] for line in membership.splitlines() if line.startswith('0::'))
        if cid not in rel:
            raise RuntimeError('Docker PID/cgroup not visible in this host namespace; do not report substitute RSS or VM memory')
        cg = Path('/sys/fs/cgroup') / rel.lstrip('/')
        required = ['memory.max', 'memory.swap.max', 'memory.peak', 'memory.stat', 'memory.events', 'io.stat', 'cpu.max', 'cpuset.cpus.effective']
        values = {name: (cg / name).read_text() for name in required}
        assert values['memory.max'].strip() == '134217728'
        assert values['memory.swap.max'].strip() == '0'
        assert values['cpu.max'].strip() == '200000 100000'
        # Match the frozen harness: proc details are auxiliary and can be
        # absent; the mandatory resource evidence is the actual cgroup above.
        proc = {}
        for name in ['status', 'io']:
            path = Path(f'/proc/{pid}/{name}')
            try:
                proc[name] = path.read_text()
            except FileNotFoundError:
                proc[name] = None
        write_json(a.output_root / 'preflight.json', {'passed': True, 'docker_info': info,
                   'images': images, 'probe_command': command, 'probe_pid': pid, 'probe_cgroup': str(cg), 'probe_state': state['State'],
                   'probe_resource_files': values, 'probe_proc': proc, 'numpy_version': numpy.__version__,
                   'scope': 'Host namespace and fixed resource limits only; no SQL validation or performance claim'})
    except Exception as error:
        write_json(a.output_root / 'preflight-failure.json', {'passed': False, 'error': str(error)})
        raise
    finally:
        # docker run may time out after creating the container. Always clean
        # this unique probe name; never target another task's containers.
        try:
            docker('rm', '-f', '-v', probe, check=False)
        except (OSError, subprocess.TimeoutExpired):
            pass

    # Exactly these three textual substitutions, recorded with hashes. Keep
    # oracle, workload, timers, output consumption, limits and counters intact.
    replacements = [
        ('ROOT=pathlib.Path(__file__).resolve().parents[1]', 'ROOT=pathlib.Path(' + repr(str(a.output_root)) + ')'),
        ("ENV=dict(os.environ,DOCKER_HOST='unix:///var/tmp/minivectordb-perf-20261110/docker.sock')", 'ENV=dict(os.environ)'),
        ("pathlib.Path('/var/tmp/minivectordb-perf-20261110/data')", 'pathlib.Path(' + repr(str(a.data_root)) + ')'),
    ]
    adapted = source.decode('utf8')
    for before, after in replacements:
        if adapted.count(before) != 1:
            raise RuntimeError('Expected exactly one frozen path/config expression: ' + before)
        adapted = adapted.replace(before, after)
    generated = tool / 'bench.adapted.py'
    generated.write_text(adapted, encoding='utf8')
    command = [sys.executable, str(generated), '--images'] + [label + '=' + data['id'] for label, data in images.items()]
    command += ['--seeds'] + [str(seed) for seed in a.seeds]
    command += ['--rows', str(a.rows), '--dim', str(a.dim), '--queries', str(a.queries), '--prefix', a.prefix]
    manifest = {'frozen_sha256': sha(source), 'frozen_source': str(frozen),
                'adapter_sha256': sha(Path(__file__).read_bytes()), 'adapted_sha256': sha(generated.read_bytes()),
                'substitutions': [{'before': b, 'after': c} for b, c in replacements],
                'docker_host': env.get('DOCKER_HOST'), 'docker_context': env.get('DOCKER_CONTEXT'),
                'output_root': str(a.output_root), 'data_root': str(a.data_root),
                'images': images, 'command': command, 'preflight_only': a.preflight_only,
                'limits_unchanged': True, 'oracle_and_timers_unchanged': True,
                'benchmark_scope': 'Local comparison only, not official scorer or result guarantee'}
    write_json(a.output_root / 'adapter-manifest.json', manifest)
    if a.preflight_only:
        print('Preflight passed; no SQL benchmark executed. ' + str(a.output_root), flush=True)
        return 0
    with (a.output_root / 'runner.stdout.log').open('wb') as out, (a.output_root / 'runner.stderr.log').open('wb') as err:
        result = subprocess.run(command, env=env, stdout=out, stderr=err)
    manifest['exit_code'] = result.returncode
    write_json(a.output_root / 'adapter-manifest.json', manifest)
    print('Benchmark exit code ' + str(result.returncode) + '; inspect ' + str(a.output_root), flush=True)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
