from pathlib import Path
def edit(path, replacements):
    p = Path("src") / path
    s = p.read_text()
    for before, after in replacements:
        if s.count(before) != 1:
            raise ValueError((path, before, s.count(before)))
        s = s.replace(before, after)
    p.write_text(s)
edit("storage.hpp", [("private:\n", """  struct ReadMapping {
    std::shared_ptr<const char> data;
    uint64_t size = 0;
  };
  ReadMapping map_committed_for_probe() const;
  void scan_with_offsets_for_probe(const std::string &table,
      const std::function<void(int64_t, const std::string &, uint64_t)> &fn) const;
private:
""")])
edit("storage.cpp", [
("#include <sys/file.h>", "#include <sys/file.h>\n#include <sys/mman.h>"),
("""void Store::scan(
    const std::string &table,
    const std::function<void(int64_t, const std::string &)> &fn) const {""", """Store::ReadMapping Store::map_committed_for_probe() const {
  const auto &s = *impl_;
  s.check();
  if (s.transaction || s.statement || s.end != s.durable_end ||
      s.end == 0 || s.end > 16 * 1024 * 1024)
    return {};
  struct stat st{};
  if (::fstat(s.fd, &st) != 0 || !S_ISREG(st.st_mode) ||
      st.st_size < 0 || uint64_t(st.st_size) != s.end)
    return {};
  void *address = ::mmap(nullptr, s.end, PROT_READ, MAP_PRIVATE, s.fd, 0);
  if (address == MAP_FAILED) return {};
  return {std::shared_ptr<const char>(static_cast<const char *>(address),
      [size=s.end](const char *p){::munmap(const_cast<char *>(p), size);}), s.end};
}
void Store::scan(
    const std::string &table,
    const std::function<void(int64_t, const std::string &)> &fn) const {
  scan_with_offsets_for_probe(table, [&](int64_t key, const std::string &data,
                                         uint64_t){fn(key, data);});
}
void Store::scan_with_offsets_for_probe(
    const std::string &table,
    const std::function<void(int64_t, const std::string &, uint64_t)> &fn) const {"""),
("      fn(key, s.load(ref));", "      fn(key, s.load(ref), ref.offset);")])
edit("exact_cache.hpp", [
("  std::vector<float> vectors;", """  std::vector<float> vectors;
  bool row_major = false;
  std::shared_ptr<const char> mapped;
  std::vector<uint64_t> vector_offsets;
  bool external_layout() const {return row_major || bool(mapped);}
  const char *row_bytes(size_t row) const {
    if(mapped) return mapped.get()+vector_offsets[row];
    return reinterpret_cast<const char *>(vectors.data()+row*dim);
  }
  float component(size_t row,size_t d) const {
    if(!external_layout()) return vectors[index(row,d)];
    float f;
    std::memcpy(&f,row_bytes(row)+d*sizeof(float),sizeof(float));
    return f;
  }"""),
("""  explicit Compact(const Plan& p):dim(p.dim),count(p.count),vector_column(p.vector_column),
                                 text_max(p.text_max) {""", """  explicit Compact(const Plan& p,bool rows=false,std::shared_ptr<const char> file={})
      :dim(p.dim),count(p.count),vector_column(p.vector_column),row_major(rows),
       mapped(std::move(file)),text_max(p.text_max) {"""),
("    vectors.resize(((count+3)/4)*dim*4);", """    if(mapped) vector_offsets.resize(count);
    else vectors.resize(row_major ? count*dim : ((count+3)/4)*dim*4);"""),
("bytes+=keys.capacity()*sizeof(int64_t)+vectors.capacity()*sizeof(float);", """bytes+=keys.capacity()*sizeof(int64_t)+vectors.capacity()*sizeof(float);
    bytes+=vector_offsets.capacity()*sizeof(uint64_t);"""),
("result[d]=vectors[index(row,d)]", "result[d]=component(row,d)"),
("double(vectors[index(row,d)])-double(q[d])", "double(component(row,d))-double(q[d])"),
("void fill(size_t i,int64_t key,const std::vector<Cell>& row) {", "void fill(size_t i,int64_t key,const std::vector<Cell>& row,uint64_t offset=0) {"),
("    for(size_t d=0;d<dim;++d) vectors[index(i,d)]=v[d];", """    if(mapped) vector_offsets[i]=offset;
    else if(row_major) std::memcpy(vectors.data()+i*dim,v.data(),dim*sizeof(float));
    else for(size_t d=0;d<dim;++d) vectors[index(i,d)]=v[d];"""),
("    for(float value:vectors) {", """    for(size_t row=0;row<count;++row) for(size_t d=0;d<dim;++d) {
      const float value=component(row,d);"""),
("double(vectors[index(row,d)])*inverse", "double(component(row,d))*inverse"),
("""inline void distances4(const Compact& cache,const size_t* rows,""", """#if (defined(__x86_64__) || defined(__i386__)) && defined(__GNUC__)
__attribute__((target("avx2,no-fma")))
inline void distances4_row_major(const Compact& cache,const size_t* rows,
                                 const std::vector<float>& q,double* out) {
  const char *p[4] = {cache.row_bytes(rows[0]),cache.row_bytes(rows[1]),
                      cache.row_bytes(rows[2]),cache.row_bytes(rows[3])};
  __m256d total = _mm256_setzero_pd();
  size_t d=0;
  auto add_dimension = [&](const __m128& values,size_t i)
      __attribute__((target("avx2,no-fma"))) {
    const __m256d diff = _mm256_sub_pd(_mm256_cvtps_pd(values),_mm256_set1_pd(double(q[i])));
    total = _mm256_add_pd(total,_mm256_mul_pd(diff,diff));
  };
  for(; d+4<=q.size();d+=4) {
    __m128 a,b,c,e;
    std::memcpy(&a,p[0]+d*4,sizeof(a)); std::memcpy(&b,p[1]+d*4,sizeof(b));
    std::memcpy(&c,p[2]+d*4,sizeof(c)); std::memcpy(&e,p[3]+d*4,sizeof(e));
    _MM_TRANSPOSE4_PS(a,b,c,e);
    add_dimension(a,d); add_dimension(b,d+1);
    add_dimension(c,d+2); add_dimension(e,d+3);
  }
  for(; d<q.size();++d) {
    add_dimension(_mm_set_ps(cache.component(rows[3],d),cache.component(rows[2],d),
                            cache.component(rows[1],d),cache.component(rows[0],d)),d);
  }
  _mm256_storeu_pd(out,_mm256_sqrt_pd(total));
}
#endif
inline void distances4(const Compact& cache,const size_t* rows,"""),
("  if(available()) {distances4_avx2(cache,rows,q,out);return;}", """  if(available()) {
    if(cache.external_layout()) distances4_row_major(cache,rows,q,out);
    else distances4_avx2(cache,rows,q,out);
    return;
  }"""),
("  if(available()) {distances8_avx2(cache,rows,q,out);return;}", """  if(cache.external_layout()) {
    distances4(cache,rows,q,out);
    distances4(cache,rows+4,q,out+4);
    return;
  }
  if(available()) {distances8_avx2(cache,rows,q,out);return;}"""),
("  distances8_contiguous_avx2(cache,row,q,out);", """  if(cache.external_layout()) {
    const size_t rows[8]={row,row+1,row+2,row+3,row+4,row+5,row+6,row+7};
    distances8(cache,rows,q,out);
    return;
  }
  distances8_contiguous_avx2(cache,row,q,out);""")])
edit("engine.cpp", [
("#include <cstdlib>", "#include <cstdlib>\n#include <cstdio>"),
("""  store_.close();
  *cache_ = Cache{};""","""  *cache_ = Cache{};
  store_.close();"""),
("""        const bool screen=!descending && exact::fp32_screen_available(view.dim);
        auto quantized=exact::prepare_quantized_query(view,projection.query,screen);""",
"""        const bool screen_capable=!descending && exact::fp32_screen_available(view.dim);
        auto quantized=exact::prepare_quantized_query(view,projection.query,screen_capable);
        const bool screen=screen_capable && (!view.external_layout() || quantized.codes);"""),
("""            auto view = std::make_unique<exact::Compact>(plan);
            size_t count = 0;
            store_.scan(st.table, [&](int64_t key, const std::string &data) {
              view->fill(count++, key, unpack_row(data, schema));
            });
            if (count != plan.count)
              throw Error("CORRUPTION", "exact cache row count changed");
            view->prepare_quantized_codes();""",
"""            const char *raw_mode = std::getenv("MVDB_SLIM_PROBE");
            const std::string_view mode = raw_mode ? raw_mode : "";
            const bool probe = !descending && !store_.in_transaction() &&
                               plan.dim == 128 && plan.count;
            auto mapping = probe && mode == "mapped" ?
                store_.map_committed_for_probe() : Store::ReadMapping{};
            const bool row_major = probe && mode == "row";
            auto view = std::make_unique<exact::Compact>(plan, row_major, mapping.data);
            size_t count = 0;
            auto fill = [&](int64_t key, const std::string &data, uint64_t offset) {
              if (mapping.data) {
                Reader reader{data};
                for (size_t c=0; c<projection.col; ++c)
                  if (schema.columns[c].type == Type::BigInt) reader.num(8);
                  else { const size_t length=reader.num(4); reader.need(length); reader.pos+=length; }
                const size_t length=plan.dim*sizeof(float);
                reader.need(length);
                if (offset > mapping.size || reader.pos > mapping.size-offset ||
                    length > mapping.size-offset-reader.pos)
                  throw Error("CORRUPTION", "mapped vector exceeds journal");
                offset += reader.pos;
              }
              view->fill(count++, key, unpack_row(data, schema), offset);
            };
            if (mapping.data) store_.scan_with_offsets_for_probe(st.table, fill);
            else store_.scan(st.table, [&](int64_t key,const std::string& data){fill(key,data,0);});
            if (count != plan.count)
              throw Error("CORRUPTION", "exact cache row count changed");
            view->prepare_quantized_codes();
            if (view->external_layout() && view->quantized_codes)
              std::fprintf(stderr,"SLIM_PROBE %s\\n",mapping.data ? "mapped" : "row");""")])

