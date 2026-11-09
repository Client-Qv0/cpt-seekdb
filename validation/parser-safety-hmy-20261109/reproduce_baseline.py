"""Record the V2 control's actual response and persisted state for the defect."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path('tests').resolve()))
import acceptance as core

p = argparse.ArgumentParser()
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
if args.output.exists():
    raise SystemExit('Refusing to overwrite existing evidence')
core.BINARY = args.binary.resolve()
records = []
with tempfile.TemporaryDirectory(prefix='mvdb-comment-repro-') as temp:
    directory = Path(temp) / 'data'
    db = core.Database(directory)
    try:
        for sql in (
            'CREATE TABLE comment_guard (id BIGINT PRIMARY KEY, n BIGINT);',
            'INSERT INTO comment_guard VALUES (1,10),(2,20);',
            'SELECT id,n FROM comment_guard ORDER BY id;',
            'DELETE FROM comment_guard WHERE id=1--2;',
            'SELECT id,n FROM comment_guard ORDER BY id;',
        ):
            records.append({'sql': sql, 'response': db.execute(sql)})
    finally:
        db.close()
    db = core.Database(directory)
    try:
        sql = 'SELECT id,n FROM comment_guard ORDER BY id;'
        records.append({'phase': 'after_restart', 'sql': sql, 'response': db.execute(sql)})
    finally:
        db.close()
if records[3]['response'].get('ok') is not True or records[3]['response'].get('affected') != 1:
    raise AssertionError('Control did not reproduce the successful DELETE')
if records[-1]['response'].get('rows') != [[2, 20]]:
    raise AssertionError('Control did not reproduce the post-restart state')
args.output.write_text(json.dumps({'scope': 'V2 control; local development protocol', 'records': records},
                                  ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('baseline: DELETE unexpectedly succeeded, affected=1, persisted rows=[[2, 20]]')
