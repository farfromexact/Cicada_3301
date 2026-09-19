# 2026-09-19 仓库清理与接续入口精简

用户要求清理无用内容，并询问是否每次交流都需要重读全仓库。日常接续不需要通读：先读当前状态，用编号/关键词定位相关证据即可。此前STATE和NEXT堆叠了长篇历史与过期下一步，确实造成重复阅读。

## 入口整理

- `STATE.md`：37,488字节/260行压缩为2,250字节/26行，保留当前结论、边界和证据入口。
- `hypotheses/NEXT.md`：16,198字节/111行压缩为866字节/12行，只保留当前接续流程。
- 两份旧文件分别逐字节保存为根目录 `STATE_HISTORY.md`、`hypotheses/NEXT_HISTORY.md`，原相对链接仍有效，哈希见 `20260919-cleanup-history.json`。
- `AGENTS.md`、`prompts/continue.md`、README明确按需检索，禁止为接续批量读取旧日志，也不再向STATE追加整篇历史报告。
- `.rgignore`让默认代码搜索跳过运行产物、原始资料、临时目录和历史快照；不删除或屏蔽直接文件访问。查证据时指定路径并使用 `rg --no-ignore`。
- `.gitignore`新增 `/.validation/`，防止临时解压副本再次入库。本次发现的227个已跟踪临时副本文件从工作区移除，待后续正常提交记录；没有执行git提交、清空索引或改写历史。

OpenAI官方说明Codex会先加载适用的AGENTS.md指导；它不是要求把仓库正文全部读一遍。本文关于本仓库读取路径的安排由实际文件和本次修改确定。参考：[OpenAI Docs：AGENTS.md](https://developers.openai.com/zh-Hans/docs/agent-configuration/agents-md)。

## 实际清理

逐文件校验并删除7个明确目标，609文件、74,774,619字节（71.31 MiB）：

- `.validation/feed010-portable`
- `tmp/bundle-round001`
- `tmp/feed001-portable-check`
- `tmp/pdfs/rendered`
- `scripts/__pycache__`、`src/lp_lab/__pycache__`、`tests/__pycache__`

前三个解压副本中344个文件与原始运行ZIP逐字节相同；96个独有回放文件先存入 `runs/portable-replay-retained-20260919.zip`，保留完整原相对路径，CRC和逐字节核对通过。其余是可再生的缓存及21页PDF预览PNG。全部609个源文件在删除前再次核对SHA-256，目标绝对路径确认位于仓库内，无符号链接/reparse point。

新保留包4,762,379字节；扣除该包后、尚未计本次维护记录与必需回归产物，释放70,012,240字节（66.77 MiB）。不把该数称为最终仓库净减量，因为回归会重新生成缓存和完整复现包。

保留唯一PDF报告、生成脚本、原图/转写、来源下载、上游仓库以及全部原始实验runs/ZIP。旧实验“失败”不等于文件无用；没有删除失败证据或改写历史哈希。

清单：[逐文件来源与哈希](20260919-cleanup-inventory.json)；执行：[删除结果](20260919-cleanup-execution.json)。清理后回归记录见 `20260919-cleanup-validation.json`。

清理后完整回归 `runs/20260919T113557.071312Z` passed：193项测试、6子命令全退出0、108个来源校验；源历史快照哈希和短入口链接检查通过。回归按现有规范新增完整复现包并再生缓存，因此不把清理前释放量当成最终磁盘净减量。未改变任何密码学结论、实验标准或未解页覆盖。
