import pathlib,shutil,json,hashlib,statistics,re
R=pathlib.Path(__file__).resolve().parent
S=R/'candidate';assert not S.exists();shutil.copytree(R/'baseline',S)
p=S/'src/exact_cache.hpp';old=p.read_text()
before='''  const size_t start=cache.index(rows[0]);
  const __m128i indices=_mm_set_epi32(int(cache.index(rows[3])),
      int(cache.index(rows[2])),int(cache.index(rows[1])),int(start));'''
after='''  const size_t start=cache.index(rows[0]);
  const size_t second=cache.index(rows[1]), third=cache.index(rows[2]),
      fourth=cache.index(rows[3]);'''
assert old.count(before)==1
new=old.replace(before,after)
before='''    __m128 values=contiguous ? _mm_loadu_ps(cache.vectors.data()+start+d*4) :
        _mm_i32gather_ps(cache.vectors.data()+d*4,indices,4);'''
after='''    const float* values_at_dimension=cache.vectors.data()+d*4;
    // Each selected row may belong to a different AoSoA block. Independent
    // scalar loads avoid AVX2 gather overhead without changing lane order.
    __m128 values=contiguous ? _mm_loadu_ps(values_at_dimension+start) :
        _mm_setr_ps(values_at_dimension[start], values_at_dimension[second],
                    values_at_dimension[third], values_at_dimension[fourth]);'''
assert new.count(before)==1;new=new.replace(before,after);p.write_bytes(new.encode())
t=S/'tests/test_exact_cache.cpp';v=t.read_text().replace('#include <stdexcept>','#include <stdexcept>\n#include <random>')
needle='  exact::Plan overflow({Type::BigInt,Type::Vector},1,128);'
block='''  // C4: arbitrary lanes, block-crossing adjacent rows and every tail length.
  // Compare doubles bit-for-bit with ordered scalar accumulation, not tolerance.
  std::mt19937 random(41873);
  for(size_t dim: {size_t(1),size_t(2),size_t(3),size_t(4),size_t(5),
      size_t(7),size_t(31),size_t(32),size_t(33),size_t(127),size_t(128),
      size_t(129),size_t(255)}) {
    exact::Plan plan({Type::BigInt,Type::Vector},1,dim);
    std::vector<std::vector<Cell>> values;
    for(size_t i=0;i<37;++i) {
      std::vector<float> vector(dim);
      for(auto &x:vector)x=float(int(random()%200001)-100000)/131.0f;
      values.push_back({int64_t(i),std::move(vector)});plan.observe(values.back());
    }
    exact::Compact cache(plan);
    for(size_t i=0;i<values.size();++i)cache.fill(i,int64_t(i),values[i]);
    for(size_t iteration=0;iteration<100;++iteration) {
      std::vector<float> q(dim);
      for(auto &x:q)x=float(int(random()%200001)-100000)/73.0f;
      std::vector<std::array<size_t,4>> groups{{0,1,2,3},{1,2,3,4},{3,4,7,8},
        {0,5,10,15},{1,6,11,16},{36,0,35,17},{36,36,0,0}};
      for(size_t k=0;k<8;++k)groups.push_back({random()%37,random()%37,random()%37,random()%37});
      for(const auto& ids:groups) {
        double output[4];exact::distances4(cache,ids.data(),q,output);
        for(size_t lane=0;lane<4;++lane) {
          double scalar=cache.distance(ids[lane],q);
          require(std::memcmp(&scalar,output+lane,sizeof(double))==0);
        }
      }
      for(size_t tail=1;tail<=3;++tail)
        for(size_t lane=0;lane<tail;++lane) {
          auto row=37-tail+lane;double expected=0;
          auto& vector=std::get<std::vector<float>>(values[row][1]);
          for(size_t d=0;d<dim;++d){double x=double(vector[d])-double(q[d]);expected+=x*x;}
          expected=std::sqrt(expected);double actual=cache.distance(row,q);
          require(std::memcmp(&expected,&actual,sizeof(double))==0);
        }
    }
  }
'''
assert v.count(needle)==1;t.write_bytes(v.replace(needle,block+needle).encode())
micro=[json.loads(x) for x in (R/'runtime/micro.stdout.jsonl').read_text().splitlines()]
summary={}
for case in ['aligned','stride5','random']:
 rows=[x for x in micro if x['case']==case]
 summary[case]={'median_reduction':statistics.median(1-x['loads_seconds']/x['gather_seconds'] for x in rows),'wins':sum(x['loads_seconds']<x['gather_seconds'] for x in rows),'rounds':rows}
summary['filter_only_median_seconds_per_full_pass']=statistics.median(x['seconds']/1000 for x in micro if x['case']=='filter_only')
summary['scope']='whole-phase microbenchmark only; 200 repetitions per distance case, 1000 filter passes; not end-to-end SQL gain'
asm=(R/'runtime/micro.asm').read_text()
def function(name):
 m=re.search(r'^\w+ <'+name+r'[^\n]*>:\n',asm,re.M);assert m
 rest=asm[m.end():];stop=re.search(r'^\w+ <',rest,re.M)
 return rest[:stop.start()] if stop else rest
loads=function('scalar_loads4');gather=function('mvdb::exact::distances4_avx2')
assert 'vgather' not in loads and 'vgather' in gather
assert not re.search(r'v(?:f[nm]*madd|f[nm]*msub|fmadd|fmsub)',loads+gather)
assert all(x in loads for x in ['vmulpd','vaddpd','vsqrtpd'])
summary['micro_assembly']={'loads_has_gather':False,'baseline_has_gather':True,'FMA_in_both':False,'loads_has_separate_mul_add_sqrt':True}
(R/'micro-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
manifest=[]
for f in S.rglob('*'):
 if f.is_file():manifest.append({'path':str(f.relative_to(S)).replace('\\','/'),'sha256':hashlib.sha256(f.read_bytes()).hexdigest()})
(R/'candidate-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({k:{'median_reduction':v['median_reduction'],'wins':v['wins']} for k,v in summary.items() if k in ['aligned','stride5','random']}))
