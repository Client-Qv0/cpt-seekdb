#!/usr/bin/env python3
"""Local public-assertion bridge; NOT the official transport or ANN implementation."""
import argparse,json,math,subprocess,tempfile,select,hashlib
from pathlib import Path

def equal(a,b):
 if isinstance(b,float):return isinstance(a,(int,float)) and math.isfinite(a) and math.isclose(a,b,rel_tol=1e-5,abs_tol=1e-5)
 if isinstance(b,list):return isinstance(a,list) and len(a)==len(b) and all(equal(x,y) for x,y in zip(a,b))
 return type(a)==type(b) and a==b

def compare_rows(actual,expected,unordered=False):
 if not unordered:return equal(actual,expected)
 if len(actual)!=len(expected):return False
 remaining=list(actual)
 for row in expected:
  for i,value in enumerate(remaining):
   if equal(value,row):remaining.pop(i);break
  else:return False
 return True

class Database:
 def __init__(self,binary,directory):
  self.errors=tempfile.TemporaryFile();self.p=subprocess.Popen([str(binary),'--data-dir',str(directory),'--dev-protocol'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.errors,text=True,bufsize=1)
 def query(self,sql):
  self.p.stdin.write(sql+'\n');self.p.stdin.flush()
  if not select.select([self.p.stdout],[],[],30)[0]:raise TimeoutError(sql)
  return json.loads(self.p.stdout.readline())
 def close(self):
  try:
   self.p.stdin.close(); code=self.p.wait(timeout=15); assert code==0,code
  finally:
   if self.p.poll() is None:self.p.kill();self.p.wait()
   self.p.stdout.close();self.errors.close()

def main():
 p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True);p.add_argument('--package',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();binary=a.binary.resolve();manifest=json.loads((a.package/'manifest.json').read_text());results=[]
 for case in manifest['cases']:
  record={'id':case['id'],'checks':[],'passed':False};db=None
  try:
   with tempfile.TemporaryDirectory(prefix='mvdb-public-') as directory:
    db=Database(binary,directory);expected=json.loads((a.package/case['result']).read_text()); index=0;mode='exact'
    for line in (a.package/case['test']).read_text().splitlines():
     sql=line.strip()
     if not sql:continue
     if sql=='--restart':db.close();db=None;db=Database(binary,directory);continue
     if sql=='--mode ann':mode='ann-exact-fallback';continue
     if sql.startswith('--'):raise ValueError('Unknown driver instruction '+sql)
     want=expected[index];got=db.query(sql);index+=1;issues=[]
     if 'error' in want:
      if got.get('ok') is not False or not got.get('code'):issues.append('expected nonempty error code')
     else:
      if got.get('ok') is not True:issues.append('expected success')
      if 'affected_rows' in want and got.get('affected')!=want['affected_rows']:issues.append('affected_rows')
      if 'columns' in want and got.get('columns')!=want['columns']:issues.append('columns')
      if 'rows' in want and (not isinstance(got.get('rows'),list) or not compare_rows(got['rows'],want['rows'],want.get('unordered',False))):issues.append('rows')
     record['checks'].append({'sql':sql,'expected':want,'actual':got,'mode':mode,'issues':issues})
    assert index==len(expected)==case['statements'],(index,len(expected),case['statements'])
    db.close();db=None;record['passed']=all(not c['issues'] for c in record['checks'])
  except Exception as error:record['error']=repr(error)
  finally:
   if db is not None:
    try:db.close()
    except Exception as error:record['cleanup_error']=repr(error);record['passed']=False
  results.append(record)
 report={'scope':'Local development bridge only; official transport not verified; ann directive uses existing exact backend, not ANN coverage. Error semantic mapping not frozen: require failure and nonempty code.','binary':str(binary),'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'manifest_version':manifest['version'],'cases':results,'passed':all(c['passed'] for c in results),'statements':sum(len(c['checks']) for c in results)};a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':report['passed'],'cases':len(results),'statements':report['statements']}));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
