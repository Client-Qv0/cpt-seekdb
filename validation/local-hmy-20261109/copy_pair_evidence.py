"""Copy generated evidence, excluding root-owned, reproducible DB data files."""
from pathlib import Path
import shutil
import sys

source, target = map(Path, sys.argv[1:])
files = 0
for path in source.rglob('*'):
    relative = path.relative_to(source)
    if 'data' in relative.parts or not path.is_file():
        continue
    destination = target / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    files += 1
print(f'copied {files} evidence files; database data directories omitted')
