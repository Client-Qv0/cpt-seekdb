"""Add verified provenance/context without rewriting historical material."""
from pathlib import Path
import argparse, copy, hashlib, json
from validate_material import BASE, ROOT, resolve, strict_json

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base-material',type=Path,default=BASE)
parser.add_argument('--output-material',type=Path,default=ROOT/'agent/conversation.json')
args=parser.parse_args()
old=strict_json(args.base_material.read_bytes())
trace=json.loads((ROOT/'provenance/source-trace.json').read_bytes())
context=json.loads((ROOT/'provenance/context-repair.json').read_bytes())

header={
 'source':'agent_material_edit',
 'recorded_client_date':'2026-11-11',
 'parent_material_commit':'6f0cbb16949f415a681b1e97cf34ca98cb6e04f2',
 'production_source_commit':'87c2778ed0688e6e56152baf02bc4f4355667458',
 'scope':'本轮补充已核验的文字来源、现有记录的上下文和此前遗漏的用户版本交接反馈。没有改写旧原话、结果或归因记录；没有新增生产优化或官方提测。',
 'coverage':'本文件由历史摘录、工具结果和明确归因的摘要组成，不是完整聊天导出。新增版本交接片段保留相邻纠正、响应和推送结果；其余未恢复的原问题仍明确缺失。',
 'authorship':'用户转发与文字原创分开记录。六段已回读定位的技术指令或结果转述，原作者是建议方 Agent；旧 source 表示执行对话中的消息来源，邻近 verified_origin_20261111 补充文字作者。',
 'material_reading_status':'本地可以核对文件格式、内容及来源。此前平台只有“本项没有有效原始分”，未获得具体失败状态；本次没有官方语义评审结果。'
}
feedback={
 'source':'verified_chat_excerpts_and_tool_outputs',
 'source_thread_id':trace['source_thread_id'],
 'recorded_client_date':'2026-11-11',
 'event_time_scope':'从历史对话回读整理；这些事件发生在本轮材料整理之前，不是本轮重新执行。',
 'episodes':copy.deepcopy(trace['authentic_correction_episodes']),
 'scope':'用户的纠正、选择与 Agent 实际执行分别归因；未添加用户没有说过的机制解释。片段范围不是完整会话。'
}
doc={'material_revision_20261111':header,'verified_user_feedback_20261111':feedback,**copy.deepcopy(old)}
for item in trace['verified_origins']:
 assert resolve(doc,item['material_pointer'])==item['content']
 record=resolve(doc,item['material_pointer'].rsplit('/',1)[0])
 assert record['id']==item['record_id']
 record['verified_origin_20261111']={
  'wording_author':'advisory_agent',
  'delivery_in_execution_chat':'user_forwarded_or_adopted_text',
  'original_role':item['origin']['role'],
  'original_thread_id':item['origin']['thread_id'],
  'original_message_id':item['origin']['message_id'],
  'origin_kind':item['origin']['type'],
  'check':'2026-11-11 回读建议对话；该 content 与所列 Agent 消息的连续原文完全匹配。执行侧转发 ID 沿用原材料，本轮未重新回读该执行消息。'
 }
for item in trace['unresolved_origins']:
 assert resolve(doc,item['material_pointer'])==item['content']
 record=resolve(doc,item['material_pointer'].rsplit('/',1)[0])
 record['origin_search_20261111']={'source':'agent_provenance_audit','status':item['origin_status']}

brief=context['sources'][1]
brief_first=context['records'][0]['context_excerpts'][0]['content']
brief_choices=context['records'][0]['context_excerpts'][1]['content'].split(' Record current server')[0]
doc['exact_scan_li_20261110']['recovered_context_20261111']={
 'source':'agent_authored_record_in_frozen_repository',
 'source_commit':brief['source_commit'],
 'repository_path':brief['repository_path'],
 'source_sha256':brief['sha256'],
 'content':brief_first+'\n\n'+brief_choices,
 'excerpt_note':'同一文件第3行和第24行开头的两个独立原文摘录；中间其他内容未包含。',
 'original_question_text_recovered':False,
 'original_message_id_recovered':False,
 'scope':'现有 Agent 工作记录可补充精确结构优化、当前服务器和15%门槛的背景；不能据此还原提问原句或推断用户独立提出这些方案。'
}
for i,record in enumerate(context['records']):
 assert resolve(doc,record['material_user_pointer'])==record['material_user_content']
 parent=resolve(doc,record['material_user_pointer'].rsplit('/',1)[0])
 if i<3:
  parent['context_pointer_20261111']='/exact_scan_li_20261110/recovered_context_20261111'
 else:
  src=context['sources'][record['context_source_index']]
  parent['recovered_context_20261111']={
   'source':'agent_authored_record_in_frozen_repository',
   'source_commit':src['source_commit'],
   'repository_path':src['repository_path'],
   'source_sha256':src['sha256'],
   'content':record['context_excerpts'][0]['content'],
   'original_question_text_recovered':False,
   'original_message_id_recovered':False,
   'scope':'原仓库中的 Agent 时序记录摘录；不是恢复出的提问原文，不补造消息 ID。'
  }

# Clarify that these pointers refer to historical source artifacts, not this root.
source_pointer_count=0
for record in doc['official_protocol_repair_20261110']['raw_protocol_examples']['records']:
 for fragment in record['fragments']:
  if 'json_pointer' in fragment:
   fragment['json_pointer_scope']='source_artifact_identified_by_source_id'
   source_pointer_count+=1
assert source_pointer_count==7
# Compact whitespace only; every old scalar remains at its original pointer.
raw=(json.dumps(doc,ensure_ascii=False,separators=(',',':'))+'\n').encode('utf8')
assert len(raw)<=131072,('oversize',len(raw))
args.output_material.parent.mkdir(parents=True,exist_ok=True)
args.output_material.write_bytes(raw)
print(json.dumps({'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'headroom':131072-len(raw),'verified_agent_origins':len(trace['verified_origins']),'context_records':len(context['records']),'new_historical_feedback_episodes':len(feedback['episodes'])},ensure_ascii=False))
