# 自动循环 R015-B H030-v3 安全暂停审阅（2026-09-14）

## 历史核对与本轮选择

本轮先核对 `STATE.md`、`hypotheses/NEXT.md`、H016-v3/H029-v3 已完成结果、H030-v2-retry3 的 gate/observed/200条partial、`H031-pgl-full-v2.json` 和既有 reviews。没有把 H030-v2 的200条部分对照当作完整统计，也没有启动已登记但未执行的 H027/H031。

三条有界、可证伪方向的排序仍为：

1. **H030-v3 BM continuation（选中）**：不改 H030-v2 的四个 F29 视图、BM 前缀/后缀规则、holdout、maxT 或随机零假设；只验证旧200条并补齐799条。
2. **H027 相邻页零偏移复用加法流消去（未选）**：相邻页差分、同流/独立流合成 gate 和页面内随机对照尚未冻结，不能直接扫 LP2。
3. **H031-v2 全部 P1(F29) Möbius 变换（未选）**：规范已登记但尚未完成独立功效门、全映射验证和正式统计。

选择 H030 continuation 的信息增益最高：既有数据链最完整，剩余799条是已冻结随机流的缺口，且不会新增后验自由度。

## H030-v3 冻结与执行

规范见 [H030-v3](../hypotheses/H030-berlekamp-massey-v3.json)。四视图固定为 `raw`、`difference`、`position_prime_residual`、`position_totient_residual`；F29 BM 在每个自身长度至少96的视图上以 `floor(2N/3)` 拟合、最大阶 `min(16,floor(prefix/4))`，预测未拟合的后缀。LP2/50 不转成符文；发现区为 LP2/0..27，holdout 为 LP2/28..55 排除50。999条页内置换对照使用 `Random(33011521 + replicate)`，alpha 精确为 `0.01/3`，不合并或平均分批 p 值。

v3 额外冻结了旧源文件哈希、旧行0..199的逐页重放和严格输出契约。续跑前逐条重算旧页内置换的输入摘要和四视图 compact metrics，结果 [resume-source](../runs/auto-cycle-r015-H030-v3/resume-source.json) 为 `passed`；旧源记录的 `controls_completed=0` 被作为历史记录滞后字段保留，不替代 partial 的实际200条。

## 暂停结果

运行在用户要求的自然节点停止：`control-results.partial.json` 和 [checkpoint](../runs/auto-cycle-r015-H030-v3/control-checkpoint.json) 均落在575条，`next_replicate=575`，partial hash 与 checkpoint 一致。已完成：

- 合成 gate：20/20 正例通过，0/99 负例误收；
- LP2 observed：55页、220个视图、51769个符文视图检查，独立验证 `passed`；
- 对照：历史0..199逐条重放通过，新生成200..574，共575/999；
- 无 `statistics.json`，因此没有正式 negative、lead、候选或 p 值解释。

记录中的 `status=error` 只表示用户主动暂停未完成实验，不能解释为 H030 的科学阴性。当前运行、stdout/stderr、checkpoint 和 [复现包](../runs/auto-cycle-r015-H030-v3/reproduction-bundle.zip) 均保留。恢复时必须先校验三个源哈希和575条partial，再从575继续到998；不得重发或统计半成品。

