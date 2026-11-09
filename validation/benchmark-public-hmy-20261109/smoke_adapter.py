"""Exercise both existing mounted-binary and new image-binary adapter modes."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path('tests').resolve()))
import benchmark_public_validation as benchmark
import cardinality_probe as adapter
import paired_benchmark as paired

out = Path('validation/benchmark-public-hmy-20261109')
meta = json.loads((out / 'seed-3179/metadata.json').read_text())
binary = Path('/mnt/e/MiniVectorDB/production-image-minivectordb')
results = []
directory = Path(tempfile.mkdtemp(prefix='mvdb-adapter-smoke-', dir='/dev/shm'))
copied = directory / 'image-copy'
sha = benchmark.check_image_binary(meta['image_id'], binary, '/app/minivectordb', copied)
for mode in ('mounted', 'image'):
    db = adapter.ContainerDatabase(binary, directory / mode, image=meta['image_id'],
                                   socket=meta['docker_socket'], cpuset=meta['cpuset'],
                                   image_binary='/app/minivectordb' if mode == 'image' else None)
    try:
        db.query('CREATE TABLE smoke (id BIGINT PRIMARY KEY, v VECTOR(1));')
        db.query("INSERT INTO smoke VALUES (1,'[2]');")
        answer = db.query("SELECT id,L2_DISTANCE(v,'[0]') AS d FROM smoke ORDER BY d LIMIT 1;")
        assert answer['rows'] == [[1, 2]], answer
    finally:
        db.close()
    assert paired.resources(db.record)['healthy']
    results.append({'mode': mode, 'passed': True})
print(json.dumps({'binary_sha256': sha, 'directory': str(directory), 'results': results}))
