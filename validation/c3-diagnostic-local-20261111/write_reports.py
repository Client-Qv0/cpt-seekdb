import pathlib,json,hashlib,statistics,datetime,difflib
R=pathlib.Path(__file__).resolve().parent
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
a=json.loads((R/'material-audit/audit.json').read_text(encoding='utf8'))
published=json.loads((R/'material-audit/published.json').read_text())
material=f'''Agent 材料复核与无损整理（{now}）

冻结提交：{a['baseline_commit']}；agent/conversation.json，Git blob 按冻结树逐字节核对。
本轮候选只是格式空白整理，不是已证实的评分修复。

1. 结构与版本
基线：{a['baseline_bytes']} 字节，SHA256 {a['baseline_sha256']}。
候选：{a['candidate_bytes']} 字节，SHA256 {a['candidate_sha256']}。
节省 {a['baseline_bytes']-a['candidate_bytes']} 字节，距 128 KiB 上限余 {131072-a['candidate_bytes']} 字节。
严格 UTF-8、无 BOM、合法 JSON 顶层对象、无重复键、非有限数及孤立代理码位检查通过。
全部解析值完全相等，916 个字符串与 JSON pointer 全部保留；学生原话、工具结果、失败/退化/跳过、Agent判断及来源未改变。
原 tests/test_agent_material.py 字节不变（{a['tests_sha256']}），5/5 通过。该工具不是官方语义评分器。
分支 {published['branch']}；提交 {published['commit']}。
远端 API 回读 blob 与测试候选完全一致，compare 仅 agent/conversation.json 改变；生产源码、Dockerfile 及共享答题分支未改。

2. 官方规则
本轮重新获取 §4.4 / §3.4 和计分页原文，URL/时间/字节/哈希见 audit.json。
官方协议分支仍为 f4d4e26653af823a7601668802f80e374ad6643c。
默认读取 agent/conversation.json、UTF-8 顶层对象、128KiB；业务字段组织不强制。
所以没有根目录盲拷贝、伪造 summary 或分数。现有材料在结构上未发现已证实的入口缺陷。

3. 语义范围与缺口
材料明确不是完整会话导出；区分 user/student、agent、tool_output、tool_result_summary、用户转述正式结果。
当前还存在多种角色标签和历史“current_session”命名，历史范围/version_index 有解释；本次无损整理全部保留，没有把历史实验重标成新版本。
例如 /cache_amortization_li_20261111/before/content 的“不确定，先测”和 after_short 的委托决策是原话，不能改成学生掌握技术解释。
同对象 short_batch、write_read 包含失败与噪声的具体数值，decision 明确属于 agent，不是学生解释。
/exact_scan_li_20261110/agent_work 保留量化摘要、首次查询/写入/超缓存退化和跳过；不是完整原始轨迹，真实性不能仅由结构测试认证。
材料有直接嵌入的工具原文与量化摘要，也仍有外部路径；路径不能替代字符串内学习证据。没有足够原始出处时不补写学生预测、理解、复盘或缺失历史反馈。

4. 评分状态
87c2 的正式通过和原始分 3122.241181 来自交接文件的用户结果转述，本轮未独立读取平台后台；组合提示不能定位具体读取/解析/评审/复核/服务状态。
异步收到用户再次确认的 7637a037e8a44c9da8e3bd65694e4474075b5657、2026-competition-round2、2277.870638 属于另一历史提交，原 sealed audit 已绑定；不改绑到87c2。
旧7637材料20922字节的格式检查通过，但未包含后来的协议修复记录；不能用当前87c2材料替代旧提交审计。
当前仍未知实际材料读取摘要、评审轮次、状态码、复核结果或服务错误；不将“没有有效原始分”当成已确认0分。
不联系外部人员，不新增学习提问，不正式提测；本次候选不能保证获得有效分或满分。
'''
(R/'material-audit/REPORT.txt').write_text(material,encoding='utf8')
if not (R/'diagnostic-summary.json').exists():raise SystemExit('material report written; diagnostic still running')
s=json.loads((R/'diagnostic-summary.json').read_text());images=json.loads((R/'runtime/tested-images.json').read_text())
rows=s['six_rounds']
lines=['C3 定向诊断：本机 WSL 复现','',f'记录 UTC：{now}',f"冻结提交：{s['baseline_commit']}",f"基线二进制：{images['baseline']['binary_sha256']}",f"基线镜像：{images['baseline']['image_id']}",f"诊断二进制：{images['instrumented']['binary_sha256']}",f"诊断镜像：{images['instrumented']['image_id']}",'',f"六轮胜出项阶段占比中位数 {s['median_winner_fraction']*100:.4f}%，门槛5%。",'占比 = 每轮 sum(winner_ns) / 同轮1000条热查询完整JSONL请求耗时；先逐轮计算再取中位数，不平均单条比例。','过滤/无过滤分列；总阶段独立包围整个胜出行循环，不将嵌套子阶段相加冒充总计。','含子阶段chrono和计数器开销；stdio编码、写出、flush在端到端分母中，不声称C3可以节省这些耗时。','', '轮次 | seed | 基线写入s | 基线首查s | 基线热查询s | 诊断热查询s | 胜出项占比 | 过滤占比 | 无过滤占比 | 基线重启ready s']
for x in rows:
 b=x['baseline_times'];d=x['instrumented_times'];g=x['groups']
 lines.append(f"{x['round']} | {x['seed']} | {b['write_s']:.6f} | {b['first_query_s']:.6f} | {b['query_s']:.6f} | {d['query_s']:.6f} | {g['all']['winner_fraction']*100:.4f}% | {g['filtered']['winner_fraction']*100:.4f}% | {g['unfiltered']['winner_fraction']*100:.4f}% | {b['restart_ready_s']:.6f}")
lines+=['',f"过滤中位占比 {s['median_filtered_fraction']*100:.4f}%；无过滤 {s['median_unfiltered_fraction']*100:.4f}%。",f"插桩相对未插桩端到端耗时变化中位 {s['median_instrumentation_relative_e2e_change']*100:+.4f}%，这是诊断扰动/测量波动，不是优化收益。",'','各子阶段为六轮每轮1000查的累计耗时中位（非独立可直接相加的消除收益）：']
for k in ['get_ns','unpack_ns','project_ns','construct_ns','winner_ns']:
 lines.append(f"{k}: {statistics.median(x['groups']['all'][k] for x in rows)/1e6:.6f} ms")
lines+=['','实验条件：每轮新数据目录、10k记录、VECTOR(128)、FP32、VARCHAR(8)标签、每批100行、1000次Top10，半数等值过滤；seed3179/3181/3187各两轮，基线与诊断顺序交替。','固定2CPU(cpuset0,1)、128MiB、0swap、只读根文件系统、默认JSONL入口、禁网。独立oracle先生成于计时区间/cgroup外，验证实际ID顺序、重复ID、过滤、距离及Recall；完整输出消费后结束计时。','first_query是新进程的冷缓存首查，随后10次预热和1000热查询；未全局drop OS页缓存。重启ready含Docker创建和恢复，不能称纯恢复CPU耗时。',f"独立参考核验累计 {sum(x['oracle_checks'] for x in rows)} 次（包括首查、预热、热查询和重启查询）；Recall全部1.0，最大距离误差 {max(x['max_distance_error'] for x in rows):.17g}。",'原始memory.peak、memory.stat、memory.events、memory.pressure、cpu.stat、io.stat及辅助proc信息留在每轮resources.json；所有观测OOM/oom_kill为0。未用RSS代替cgroup峰值，未用数据文件大小估算物理I/O。','io.stat仅容器ready至shutdown前采样，异步回写与页缓存归属限制保留，不估算官方分。','构建第一次因禁bridge网络DNS失败，保留baseline-build.log；使用相同Dockerfile加--network host完成依赖构建，测试容器仍禁网，生产源码/Dockerfile未改。','基线重建二进制哈希与队友冻结b2501504...一致；镜像ID是本机重建，与队友镜像不同，不冒充服务器重测。','']
if s['below_gate']:
 lines+=['决策：未到5%诊断门槛，停止C3，不实现生产候选、不临时换优化。诊断插桩只用于证据，不能部署为优化版。','在本机已测负载中，即使将测得整段时间全部视为可消除，也仅约3.15%，且包含计时开销；直接缓存投影仍会有输出构造成本。这只是粗略收益空间判断，不是实际加速保证。','候选A/A、主负载/超缓存/留出性能验收、全量Release/sanitizer/公开20/强杀恢复/百万短记录资源门槛：未执行，因为没有进入C3候选实现阶段；不把历史测试搬来填本轮PASS。','本轮实测仅上述基线/诊断默认入口与其独立oracle、启动、读取、正常shutdown和重启回读；事务、强杀恢复等依旧依据原冻结报告，本轮未重跑。','下一轮建议仅作为待验证假设：优先独立诊断过滤枚举与非连续向量读取的成本。当前过滤半批仅20%记录参与距离计算，却耗时多于无过滤半批；这不足以直接确认瓶颈或批准新的实现，本轮没有实施。']
else:lines+=['决策：达到初步诊断门槛；尚需排除插桩干扰并执行后续C3实现与验收，不可称候选完成。']
lines+=['','已实测：固定源码/二进制绑定、材料等价校验、默认入口六轮诊断和参考正确性、实际cgroup资源计数。','尚未验证：平台Agent无分根因；服务器同工况复现；本轮未做的完整回归与物理I/O专属归因。','等待官方题包/平台：隐藏正式用例、官方评测原始详细报告；公开协议/20例已发布，不再把它们写成等待发布。','学习记录只保留本轮实际决定、原始工具结果和退出结论；没有补写学生理解。','大体积原始请求/输出/fixture与资源日志保存在本机 diagnostic-runs；仓库只提供摘要、清单和复现工具，不能说已随提交提供所有轨迹。']
(R/'C3_REPORT.txt').write_text('\n'.join(lines)+'\n',encoding='utf8')
diff=''
for n in ['engine.cpp','main.cpp']:
 old=(R/'baseline/src'/n).read_text().splitlines(True);new=(R/'diagnostic-source/src'/n).read_text().splitlines(True)
 diff+=''.join(difflib.unified_diff(old,new,fromfile='a/src/'+n,tofile='b/src/'+n))
(R/'diagnostic.patch').write_text(diff)
print('REPORTS_WRITTEN')
