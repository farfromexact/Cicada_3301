"""Merge completed H008 evidence into the current research index, preserving peers."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    path=ROOT/"research/knowledge.json"
    raw=path.read_bytes()
    doc=json.loads(raw)
    record=json.loads((ROOT/"runs/attempt4-H008-v1/record.json").read_text(encoding="utf8"))
    audit=json.loads((ROOT/"reviews/attempt-004-audit.json").read_text(encoding="utf8"))
    assert record["status"]=="negative" and record["complete"] and record["controls_completed"]==999
    assert not any(record["formal_lead_families"].values()) and audit["status"]=="passed"
    new=[dict(id="E008-structure",hypothesis="H008-structure-v1",outcome="negative",
              artifact="runs/attempt4-H008-v1/record.json",
              assertions={"status":"negative","complete":True,"controls_completed":999,
                          "coverage.pages":55,"coverage.runes":12956,
                          "formal_lead_families.A":False,"formal_lead_families.B":False,"formal_lead_families.C":False,
                          "strongest.A.p_adjusted":0.397,"strongest.B.p_adjusted":0.761,"strongest.C.p_adjusted":0.214},
              coverage="全部55个含符文未解页、12956符文；1595个lag1..29、55个连字符关联、1个整库四符文跨页碰撞统计，各999对照。只有这些统计及零假设下未达门槛；没有排除密码族。"),
         dict(id="E008-measurement-audit",hypothesis="H008-structure-v1",outcome="passed",
              artifact="reviews/attempt-004-audit.json",
              assertions={"status":"passed","checks":35430,"failures":[],
                          "coverage.recomputed_probabilities":1651,"coverage.control_replicates":999},
              coverage="独立原始解析、全部原始统计及已保存对照的标准化/maxT/p算术，源坐标、局部定位和68成员归档逐字节核对；不重跑未知页扫描，不是独立密码学确认。")]
    if any(x["id"] in {e["id"] for e in doc["experiments"]} for x in new):
        raise ValueError("H008 evidence is already registered")
    doc["experiments"].extend(new)
    claim=next(c for c in doc["claims"] if c["id"]=="C015")
    claim.update(status="conjecture",
        claim="多表示结构扫描仍是研究方向。H008已执行全体适用未解页的原始0..28序号结构检查：短距离相等、字面连字符关联、跨页四符文重复均未达登记门槛。GP/phi及几何表示尚未执行；相关变换不能当独立证据。",
        next_step="保留H008全部结果和选择后定位；先用有依据的已知机制检验结构测量的检出能力，或为新的结构专属机制冻结可反驳预测。不得将negative解释成所有密码/结构均排除。")
    claim["experiments"].extend(x["id"] for x in new)
    claim["evidence"].append(dict(path="reviews/attempt-004.md",anchor="三个登记的结构家族都没有达到线索门槛"))
    if path.read_bytes()!=raw:
        raise RuntimeError("Research index changed concurrently; rerun against fresh state")
    path.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(claims=len(doc["claims"]),experiments=len(doc["experiments"]),registered=[x["id"] for x in new])))


if __name__=="__main__":
    main()
