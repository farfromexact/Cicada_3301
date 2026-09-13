# Liber Primus Lab

长期、可复现、符文级的 Cicada 3301 研究仓库。当前最小闭环：LP2 56/57 已知解法回归 + 隔离答案的合成素数流搜索。
先读 [STATE.md](STATE.md) 看实际结果与边界；研究纪律见 [AGENTS.md](AGENTS.md)。

## 离线复跑

需要 Python 3.11+（本轮实际使用 Windows Python 3.12.8），核心无第三方依赖，无需 pip 安装。
在本目录执行：

```powershell
python -X utf8 scripts/run_round.py
```

命令校验 18 个来源文件哈希、运行 unittest、从原始符文复现两页、生成三个新随机密钥并运行盲搜索。
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
- `hypotheses/`：预注册规范、其他已知解法清单和三个下一轮假设。
- `runs/`：不可覆盖的运行记录；`reviews/`：本轮复核与限制。
- `prompts/`：续研指引，只是文本，不是定时任务。

原有 `github/iddqd` 等材料保留原位，并由 `.gitignore` 排除大型原始工作区。
旧 README 提到的 Dukotah、Wulfic、Taiiwo、mortlach 本地仓库本轮检查时均不存在，旧文档已存 `sources/context/legacy-*`。
不要把旧清单中的下载声明当作已核实状态。

研究入口：[CicadaSolvers QuickStart](https://www.cicadasolvers.com/quickstart/) 和
[iBotPeaches/cicada_3301](https://github.com/iBotPeaches/cicada_3301)。来源说法和本项目复现结果分开记录，详见 [来源边界](sources/README.md)。
