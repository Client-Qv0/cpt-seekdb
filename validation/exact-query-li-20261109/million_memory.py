from pathlib import Path
import importlib.util,json,time
r=Path('/opt/minivectordb-v2-query');p=r/'validation/exact-query-li-20261109';s=importlib.util.spec_from_file_location('adapter',r/'tests/cardinality_probe.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);records=[]
for kind in ['scalar','vector4']:
 for version,binary in [('control','/opt/minivectordb-v2/build-handoff/minivectordb'),('prototype',str(r/'build-query/minivectordb'))]:
  c=m.ContainerDatabase(binary,p/'memory-data'/f'{kind}-{version}',image='minivectordb-li-runtime:20261109',socket='unix:///var/run/docker.sock',cpuset='0,1');entry={'kind':kind,'version':version}
  try:
   c.query('CREATE TABLE items (id BIGINT PRIMARY KEY,x BIGINT'+(',v VECTOR(4)' if kind=='vector4' else '')+');')
   for start in range(0,1000000,1000):
    rows=[f'({i},{i%97}'+(f",'[{i%31},{i%17},{i%7},{i%3}]'" if kind=='vector4' else '')+')' for i in range(start,start+1000)];assert c.query('INSERT INTO items VALUES '+','.join(rows)+';')['affected']==1000
   for key in [0,999999]:assert c.query(f'SELECT id,x FROM items WHERE id={key};')['rows']==[[key,key%97]]
   time.sleep(1);entry['after_load']=c.capture('after_load')
   result=c.query('SELECT id,x FROM items WHERE x>=0 ORDER BY x DESC,id ASC LIMIT 8;');assert result['rows']==[[96+i*97,96] for i in range(8)]
   time.sleep(1);entry['after_scan']=c.capture('after_scan');entry['passed']=True
  finally:c.close();entry['container']=c.record;records.append(entry);(p/'million-memory.json').write_text(json.dumps(records,indent=2))
print([(e['kind'],e['version'],{a:dict(line.split() for line in e[a]['memory.stat'].splitlines())['anon'] for a in ['after_load','after_scan']}) for e in records])
