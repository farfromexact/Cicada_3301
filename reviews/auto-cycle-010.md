# 自动循环 R008 H016-v3 验证修订审阅（2026-09-14）

## 历史核对与本轮选择

H016-v1 的四个私有正例为空、连续跨页重数被重置、`dead/not_reached/compatible` 状态混用，原始 `negative` 已由 E017 撤回。H016-v2 修复了这些问题并完成 55 个含符文页、两种连续性、999 组零保持置换和独立验证，但 Astra 的只读审计发现正例仍都是单页，规范承诺的短路径 oracle 没有固定进回归，runner 也缺少统计写盘后的最终 deadline guard。

本轮先查 `research/knowledge.json`、`STATE.md`、H016-v1/v2 规范、R008 审阅和已保存运行；没有把 v2 结果重复计为新证据。候选后续方向按信息增益/未完成度排序如下：

1. H030-v2 Berlekamp–Massey：已有 gate、正式 observed 和独立验证，页内置换只完成 200/999；优先完成这条已有证据链，不改参数。
2. H027 相邻页零偏移复用加法流的消去检验：区别于 H017 页内差分和 H016 指定周期钥匙；须先做同流/独立流合成校准和 F 边界契约，尚未授权正式页对扫描。
3. H031-v2 全部 30 点 P1(F29) Möbius 变换：已登记但未运行；来源对分隔符的约束较弱，需先完成独立功效门和全映射验证。

本轮选择 H016-v3 作为验证修订，而不是扩张钥匙参数：它直接修复已审计的验证缺口，且不改变 v2 的密码学假设、统计量、随机零假设或候选门槛。下一步的研究方向选 H030-B，继续从其 checkpoint 而非重发一个无关搜索。

## H016-v3 冻结契约

规范见 [H016-v3](../hypotheses/H016-periodic-plaintext-F-state-v3.json)。固定内容为：FIRFUMFERENFE 的 13 个原始 0..28 序号、减法逆变换、初相位 0；明文 F 复制且不消费时钟，密文 0 同时保留普通非 F 路径；page-reset 与 numeric-order continuous 两分支；55 个适用页/12,956 符文/56 个统计单元；999 次固定 seed 的页内非零置换；原 maxT、`p<=0.01`、兼容页不等于候选的判定。

验证修订固定为四个两页私有正例：continuous 先整段加密再按符文切页，page-reset 每页独立从 phase 0 加密；独立 verifier 检查 8 个分页 endpoint、累计 continuous endpoint、完整摘要字段和无路控制。永久回归用正向枚举 `p=0..28` 的未截断 oracle，覆盖 13 个起始相位与长度 0–3 的全部 328,380 个输入；这不读取答案，也不进入正式随机预算。统计写盘前后均做 monotonic deadline 检查，超时产物标 `accepted=false`，不转成 negative。

## 结果与解释

正式 [运行记录](../runs/auto-cycle-r008-H016-v3/record.json) 正常结束：`inconclusive`、999/999 对照、12,956 符文、无 error/timeout，复现包已归档。独立 [验证](../runs/auto-cycle-r008-H016-v3/independent-verification.json) `passed`，4 个正例共 8 个分页 endpoint 全部通过；[deadline 检查](../runs/auto-cycle-r008-H016-v3/deadline-check.json) 为 `passed`，统计写盘前后耗时约 34.47/34.55 秒，预算 120 秒。

逐页重置仍只有 LP2/2、LP2/15、LP2/49、LP2/53 完整可达；其余 51 页死亡。continuous 在 LP2/0 的零基位置 5 死亡，后续页为 `not_reached`。无 statistic lead、无 `unsolved_page_candidates`；v3 最强 LP2/53 的 maxT `p=0.059`，LP2/2 为 `0.444`。v2 的路径细分仍可作为审计参考：四页分别有 10、4、1、2 条完整路径，但这不是明文选择。

本轮新增结论是“验证契约已加强并复现 v2 的限定 inconclusive 结果”，不是新的 LP2 解密。H016 仍不能升级为全库兼容或候选：51 页死亡反驳了“所有适用页统一使用固定 page-reset 模型”，四个局部页只能保留兼容性未决；LP2/49 的 66 符文还不覆盖其后字母数字网格。

## 复现与收束

`test_periodic_f_state_v2.py` 8/8、`test_periodic_f_state_v3.py` 3/3、py_compile 均通过；仓库 `scripts/run_round.py` 的 tests、reproduce、research、clues、math、synthetic 六项均退出 0。H016-v1/v2 原始运行和失败/修正记录均保留，v3 不覆盖它们。

后续不得在看到四页兼容后调 key、offset、period、F 策略或 page order。先完成 H030-v2 已落盘的 200/999 对照并单独审阅；H027/H031 只有在新规范、正负 gate、holdout 和独立验收冻结后才可启动。
