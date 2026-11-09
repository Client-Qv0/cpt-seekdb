import importlib.util,sys
from pathlib import Path
r=Path('/opt/minivectordb-v2-query');p=r/'validation/exact-query-li-20261109'
s=importlib.util.spec_from_file_location('oracle',r/'tests/audit_performance.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
for seed in (9143,27183):
 m.SEED=seed;sys.argv=['audit','--binary',str(r/'build-query/minivectordb'),'--benchmark-script',str(r/'tests/benchmark_local.py'),'--output',str(p/f'oracle-seed-{seed}.json')];result=m.main();assert result==0,result
