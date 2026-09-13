# 累积研究记忆

目标：让仓库逐步成为这个问题上可查询、可纠错、可复用的研究经验库。
用户可以持续提供文章、推理、片段或问题，不要求每条输入都立即启动一个大实验。

每次接收输入：

1. 原文只读快照 + 来源哈希，分配 FEED 编号；保留用户实际意图。
2. 提取可独立核查的主张，搜索已有记录，标明新增、重复、冲突或补充。
3. 关联来源、已有实验、解释与未决问题。文本联想不能自动升级为密码机制。
4. 值得试且边界明确才建立预注册实验；执行后保留原始结果、覆盖范围和失败原因。
5. 更新索引和 STATE。后来修正结论时保留原说法和变更理由，不删除失败路径。

`knowledge.json` 是当前可检索索引，`feeds/` 是输入记录；实验正文和原始输出仍在 hypotheses/runs/reviews。
用户偏好与研究方法另存 `methods.json` 和 `METHOD.md`，明确区分用户原话、助手建议及谨慎解释；不混入密码学已证实主张。
主张状态：reproduced（限定范围内复现）、source_reported（来源有说法尚未复现）、conjecture（推测）、corrected（已纠正）。
实验状态独立使用 passed/negative/error/timeout/inconclusive。文档误述、未尝试与实验阴性是三件事。

查询已有经验：

```powershell
python -X utf8 scripts/research.py find F
python -X utf8 scripts/research.py find circumference
python -X utf8 scripts/research.py validate
```

“行不通”必须有范围。例如本仓库只证实 **LP2/56、offset=0、shift=1、无跳位** 与参考有 29 处不同；
这不代表素数流、其他偏移或其他页面都已排除。复试该配置前要说明输入、实现或鉴别目标发生了什么变化。

这套记录帮助后续会话继承经验，不意味着模型被重新训练，也不会自动把经常重复的说法变成事实。
