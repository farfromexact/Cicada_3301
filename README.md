# Liber Primus Lab

长期、可复现、符文级的 Cicada 3301 研究仓库。持续接收输入，积累思路、已有尝试、失败范围和未决问题。
日常先读精简的 [STATE.md](STATE.md)，再用 `python -X utf8 scripts/research.py find <编号或关键词>` 定位相关证据；不需要通读全仓库。研究纪律见 [AGENTS.md](AGENTS.md)。
完整历史保存在 [STATE_HISTORY.md](STATE_HISTORY.md)，旧“下一步”不代表当前待办。默认 `rg` 已排除大体积证据和临时目录；确需检索时指定路径并用 `--no-ignore`。
研究记忆的入口是 [research/README.md](research/README.md) 和 [主张/实验索引](research/knowledge.json)。

## 离线复跑

需要 Python 3.11+（本轮实际使用 Windows Python 3.12.8）。基础密码模块无第三方依赖；H008结构实验及完整测试增加NumPy，固定复现环境为Python3.12.8 / NumPy1.26.4。当前环境已安装；新环境可先安装 `.[structure]`。
在本目录执行：

```powershell
python -X utf8 scripts/run_round.py
```

命令自动发现并校验全部固定来源、运行 unittest、复现 LP2 两页与 LP1 A WARNING、检查 LP1/05 方阵、数学表示和研究索引，生成三个新随机密钥并运行盲搜索。
未解页研究路线遵循 [统一、有界、以机制为主的方法](research/METHOD.md)；合成搜索仅是验证工具。
首轮正式未解批次已完成：[attempt 1 报告](reviews/attempt-001.md)。55 个含符文页的四种固定素数时钟去重后共 169 个变换，没有达到预注册线索门槛。完整回归只核验已有证据，不自动重跑未解批次。
第二轮已完成：[attempt 2 报告](reviews/attempt-002.md)。复现LP1/03-04共515符文，辨明明文F例外、跨页密钥位置及LP2/56边界时钟；26个已知页配置独立核验通过，新增未解页候选0。
第三轮已完成：[attempt 3 报告](reviews/attempt-003.md)。H007以合并的`(位置,t)`状态覆盖LP2/0–55的12956个符文；连续流在LP2/0 ordinal 235后死亡，逐页重置仅LP2/1和混合网格页LP2/49保留状态。控制与独立复核通过，但没有接受新明文。
第四轮已完成：[attempt 4 报告](reviews/attempt-004.md)。H008在55页统一检查短距离相等、连字符关联、跨页四符文重复，各999组对照均完成；家族内校正p最低0.397/0.761/0.214，无正式结构线索。三处四符文重复已定位和原图抽查，不能当作共同单词或共享key。完整回归不会重跑这批未知页诊断。
每次写入新的 `runs/<UTC时间>/`：`record.json`、原始 stdout/stderr、逐符文 trace、完整候选分数、验证结果、随机种子与代码/输入 ZIP。
不覆盖历史运行，不联网、不访问暗网、不运行上游脚本。

分别运行（输出目录必须不存在）：

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 scripts/reproduce.py --out runs/manual-reproduction
python -X utf8 scripts/synthetic_benchmark.py --out runs/manual-synthetic
python -X utf8 scripts/synthetic_benchmark.py --out runs/manual-replay --replay runs/<原运行>/synthetic
```

`--replay` 只允许生成/验证端读取旧种子。搜索 worker 只从 stdin 读取公开挑战。
保存的 `reproduction-bundle.zip` 包含当次代码和输入；解压到新目录即可执行同样的离线闭环。
`prepare_data.py` 可从固定原转写重建派生 JSON；重新获取来源不是通常的复跑步骤。

## 结构

- `sources/`：固定来源、版本、获取时间、SHA-256、原图与转写。
- `data/`：无损 token、定位、显式歧义和合成训练/保留文本。
- `src/lp_lab/`：符文、变换、参考验收、溯源、生成与验证。
- `scripts/search_worker.py`：仅公开输入的盲搜索器；受限读取。
- `tests/`：已知回归、变异/错误参数对照、信息隔离和错误/超时分类。
- `hypotheses/`：预注册规范、其他已知解法清单和下一轮假设。
- `runs/`：不可覆盖的运行记录；`reviews/`：本轮复核与限制。
- `prompts/`：续研指引，只是文本，不是定时任务。

原有 `github/iddqd` 等材料保留原位，并由 `.gitignore` 排除大型原始工作区。
旧 README 提到的 Dukotah、Wulfic、Taiiwo、mortlach 本地仓库本轮检查时均不存在，旧文档已存 `sources/context/legacy-*`。
不要把旧清单中的下载声明当作已核实状态。

研究入口：[CicadaSolvers QuickStart](https://www.cicadasolvers.com/quickstart/) 和
[iBotPeaches/cicada_3301](https://github.com/iBotPeaches/cicada_3301)。来源说法和本项目复现结果分开记录，详见 [来源边界](sources/README.md)。
