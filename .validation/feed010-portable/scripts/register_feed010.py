"""Register preserved intake evidence. Refuse duplicate IDs rather than overwrite history."""
from pathlib import Path
import datetime as dt
import hashlib
import json
ROOT=Path(__file__).resolve().parents[1]
path=ROOT/'research/knowledge.json'
doc=json.loads(path.read_text(encoding='utf8'))
if any(c['id']=='C020' for c in doc['claims']):
    raise ValueError('C020 already registered; inspect before changing')
doc['claims'].append(dict(id='C020',topic='geometry perimeter spiral within circumference unigram invariance measurement',status='reproduced',
    claim='仅LP1/05与LP1/16固定数阵，16个D4加路径反向的具名遍历各产生8条整数序列；mod29和phi格值mod29各仍8条。直方图和逐格映射保持，不能用单符文评分选择纯重排。是测量能力核查，不是隐藏读序、数阵key或完整16页解密。',
    evidence=[dict(path='hypotheses/FEED010-geometry-audit-v1.json',anchor='deterministic measurement capability audit'),dict(path='sources/feed010/user-proposal.txt',anchor='perimeter')],
    experiments=['E010-geometry-mechanics'],next_step='见reviews/feed010-operational-metaphors.md；先定义原图几何、顺序敏感指标、保持已知对称的对照及独立预测。'))
for claim in doc['claims']:
    if claim['id']=='C008':
        claim['evidence'].append(dict(path='sources/feed010/user-proposal.txt',anchor='WITHIN / OUTSIDE / CIRCUMFERENCE'))
        claim['next_step']='FEED-010将环/螺旋、自生边界key保留为未测机制；C020只核查读序等价和评分不变性。几何模式仍须原图布局与独立预测，见reviews/feed010-operational-metaphors.md。'
doc['edges'].append({'from':'C008','to':'C020','relation':'constrains_measurement_not_cipher_confirmation'})
doc['experiments'].extend([
    dict(id='E010-geometry-parser-error',hypothesis='FEED010-geometry-audit-v1',outcome='error',
         artifact='runs/feed010-geometry-audit-v1/record.json',assertions={'status':'error','exit_code':1},
         coverage='首次首块转写/附件矩阵解析因末行无LaTeX终止符报错，未获得审计结果；非密码学negative。原失败与快照保留。'),
    dict(id='E010-geometry-mechanics',hypothesis='FEED010-geometry-audit-v1',outcome='passed',
         artifact='runs/feed010-geometry-audit-v1-parserfix/audit.json',
         assertions={'status':'passed','feed_numeric_matrix_matches_pinned_transcription':True,
                     'grids.LP1/05.unique_sequences.integer_cell':8,'grids.LP1/16.unique_sequences.integer_cell':8,
                     'grids.LP1/05.controls.distinct_label_paths':16,'grids.LP1/16.controls.broken_corner_unique_sequences':16,
                     'coverage.path_view_evaluations':96,'coverage.unsolved_page_candidates':0},
         coverage='仅两座明确5x5已知数阵、32具名路径及三表示共96输出；可逆/直方图/逐格映射检查、不同坐标和破坏对称对照。无统计验收，无新明文，16原图未独立校对。')])
path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
feed_path=ROOT/'research/feeds/FEED-010.json'
feed=json.loads(feed_path.read_text(encoding='utf8'))
feed['derivation']=dict(version='feed010-review-v1',created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
    input_sha256=hashlib.sha256((ROOT/feed['source']).read_bytes()).hexdigest(),
    review_sha256=hashlib.sha256((ROOT/feed['review']).read_bytes()).hexdigest())
feed_path.write_text(json.dumps(feed,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print('Registered FEED-010; C020 is measurement evidence only.')
