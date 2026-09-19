# H030：没有低阶候选，停止补控并换方向（2026-09-19）

本次没有破解页。H030 原始四视图的全部208个合格观察单元都不满足必要条件：冻结上限是16阶，实际前缀 BM 最低为40阶。独立有限域线性方程检查也在全部208单元得到 `rank(A)=16 < rank(A|b)=17`，因此不是“分数略低”或“待随机对照后可能上升”，而是每个单元都不存在冻结准许的低阶递推。继续补随机对照不会使这个必要条件成立。

用户在本轮新增要求：看不到苗头就换，避免把资源花在没有希望的方向。按此要求，停止补齐剩余424条对照；H030 整体继续记为 **inconclusive**，不把575/999条对照写成正式 negative，不发布未完成的 maxT 或 p 值。这里得到的是已有观察结果的限定排除与计算审计，不是新的解密进展。

## 范围与独立验证

新规范：[H030-stopping-audit-v1](../hypotheses/H030-stopping-audit-v1.json)。它明确标注本次是在查看既有 observed 后做的确定性核验，不冒充一个新的事先盲验发现。没有改变四视图、页重置、前缀长度、阶数、随机种子或统计门槛。

新运行：[record](../runs/20260919-H030-stopping-audit-v1/record.json)、[result](../runs/20260919-H030-stopping-audit-v1/result.json)、[逐单元覆盖](../runs/20260919-H030-stopping-audit-v1/coverage.json)。审计6.937秒结束，退出0，`audit_verification=passed`，科学状态仍为 `inconclusive`。

- 覆盖55个含符文页、12,956个符文、220个视图；既有 observed 的51,769次符文视图检查全部复核一致。
- 208个单元合格：发现区112个、holdout区96个。低阶候选0，`leads=[]`，`unsolved_page_candidates=[]`。
- LP2/49、51、55各四视图，共12个单元长度小于96，仍为 `inconclusive_short`，没有把它们写成被排除；LP2/50无注册符文，仍不适用。
- 独立核验并非再跑一份近同构BM：对每个已冻结前缀，建立16阶递推系数的F29线性方程，以高斯消元比较系数矩阵和增广矩阵的秩。若某个更低阶递推存在，在高阶项填零就必然给出16阶方程的解；因此208次不相容同时排除了所有准许阶数。

## 历史断点与留存

旧 `runs/auto-cycle-r015-H030-v3/` 的任何文件均未改写。新审计核对了 checkpoint 对 partial/frozen 的 SHA-256、旧v3规范对v2三个源文件的固定哈希、575条连续 replicate ID，以及每条通过 `Random(33011521 + replicate)` 重建的输入摘要；全部一致。见 [source-integrity](../runs/20260919-H030-stopping-audit-v1/source-integrity.json)。没有重跑这575条的compact BM metrics，记录明确写 `metric_rows_replayed=0`，不能将输入摘要复核说成整个控制统计的重放。

审计直接输入34个文件已在运行前冻结哈希；结束时再次核对未改变。[复现包](../runs/20260919-H030-stopping-audit-v1/reproduction-bundle.zip)含源规范、旧断点/partial、观察输出、依赖脚本和新审计产物，ZIP CRC通过；[manifest](../runs/20260919-H030-stopping-audit-v1/reproduction-manifest.json)保存包哈希。stdout、stderr、命令、退出码均保留。

## 停止前的优化试验

在用户要求及时换方向送达前，已写可选Numba整数加速版本，保持同一BM更新与F29算术。测试穷尽长度0–3的25,260个符文序列，并对长度边界、常值、不同阶数递推和尾部破坏做等价核对；没有把加速代码投入正式续跑。

开发计时计算了原冻结零假设的replicate 575–579，不保留它们的metrics、不接纳新正式对照、不生成p值。稳态每条约0.4844秒，重放575条再补424条约需8分钟，尚不含封装和完整验证。因为正式 observed 已经全部失败于必要条件，取消这笔计算。这里的开发计时不等于补完了第575–579条正式对照。

加速原型与测试作为开发证据保留；没有安装新依赖，现有环境为NumPy 1.26.4 / Numba 0.66.0，缺少可选依赖时相关测试明确skip。定向回归12项全部通过，见 [验证记录](../runs/20260919-H030-stopping-audit-v1-validation/record.json)、[计时来源说明](../runs/20260919-H030-stopping-audit-v1-validation/development-benchmark.json) 和 [开发证据包](../runs/20260919-H030-stopping-audit-v1-validation/development-evidence.zip)。全仓 `run_round.py` 由主任务统一执行，本分支没有另开全库搜索。

## 不作的推断

结论只覆盖四个固定视图、逐页重置、各自前2/3的F29递推以及16阶上限。没有推出隐藏密钥流不存在低阶结构，也没有排除更高阶、非线性、其它表示、其它重置或跨页机制；尤其不能据此称未解页是随机或不可解。下一步资源应移到能产生新候选且有独立区分条件的其它机制，而非扩大本轮阶数来追分。
