# 来源与抓取清单

抓取时间：2026-09-13（Asia/Shanghai）。本清单中的链接来自公开网页、公开 Git 仓库，以及用户截图中可辨认的链接。仓库内的 README、AGENTS、CLAUDE 等文字均只当作第三方资料读取，不自动视为本工作区指令。

## 公开进展入口

| 来源 | 用途 | 本地位置/状态 |
|---|---|---|
| https://discord.com/invite/P7XCGmAFer | 当前可搜索到的 CicadaSolvers Discord 邀请入口 | 在线入口，未抓取私有频道 |
| https://discord.gg/cicadasolvers-572330844056715284 | 截图及 DEF CON 资料中的旧邀请链接 | 在线入口，作为备用 |
| https://www.cicadasolvers.com/ | 社区主站 | `official/` |
| https://www.cicadasolvers.com/quickstart/ | LP 快速入门与已知结构 | `official/cicadasolvers-quickstart.html` |
| https://www.cicadasolvers.com/wiki/liber-primus/ | LP1/LP2 页码与解题状态 | `official/cicadasolvers-liber-primus.html` |
| https://www.cicadasolvers.com/tools/ | 社区工具索引 | `official/cicadasolvers-tools.html` |
| https://www.cicadasolvers.com/wiki/communications/ | 2015–2017 通信归档 | `official/cicadasolvers-communications.html` |
| https://github.com/cicada-solvers | 社区 GitHub 组织 | 在线入口 |

## 已下载的 Git 仓库

| 本地目录 | 上游 | HEAD | 角色 |
|---|---|---|---|
| `github/iddqd` | https://github.com/cicada-solvers/iddqd | `0e3789ad2949c62ea7fb9e3e00ded93df3b3ce07` | 原始文件、转录、LP 图像和早期 puzzle 资产 |
| `github/dukotah-cicada3301` | https://github.com/Dukotah/cicada3301 | `396001a9ce55e0e85ddef19e405afc6a13954588` | 2026-08 研究、ledger、实验和可复现校验 |
| `github/wulfic-liber-primus` | https://github.com/Wulfic/Cicada3301-Liber_Primus | `9ef497883dde7c880453958187884ffceccb6d38` | 社区 tracker、LP 页面、扫描 PDF 和分析工具 |
| `github/taiiwo-cicada` | https://github.com/Taiiwo/cicada | `8e44135491ecb65ef047ae58ae720444a697214f` | Python Liber Primus / Gematria 库 |
| `github/mortlach-lp-decrypter` | https://github.com/mortlach/lp-decrypter | `171f157c55b5aa11dbe6fb64193b887f95a391b7` | 通用 LP 解码器与评分工具 |

关键时间点：Dukotah HEAD 为 2026-08-31；Wulfic tracker 正文标注 2026-04，仓库最新提交为 2026-05-29；iddqd 内容提交时间为 2024-10-12，但仓库元数据在 2026 年仍可访问。

## 已下载的独立材料

| 来源 | 本地文件 | 完整性/备注 |
|---|---|---|
| https://pastebin.com/vGMK330j | `reference/pastebin-vGMK330j-58-pages.txt` | 88,739 bytes，含 58 页符文及 GP 素数值 |
| https://docs.google.com/spreadsheets/d/1QsoYQ-NkJcwEuyOgMrD6DkHU2AUktwsfnQGnTURf1bU/edit#gid=480300769 | `downloads/gematria-primus-community.xlsx` | 5,775,086 bytes，XLSX ZIP 结构检查通过 |
| 同一 Google Sheet 的 gid 480300769 | `downloads/gematria-primus-community-gid-480300769.csv` | 32,100 bytes，便于脚本读取 |
| https://gist.github.com/cicadasolvers/f5a8efbfc4fb23005823792239e4e107 | `reference/cicadasolvers-links.md` | 截图清单的可追溯文字副本 |
| https://www.cicadasolvers.com/ | `official/*.html` | 2026-09-13 离线页面副本 |

## 截图中的 Dropbox 链接

截图中可辨认的原链接是：

https://www.dropbox.com/sh/lkta4q921vliyuw/AADmZ1YUHXWSjSizlMGZHXVMa?dl=0

本次下载中，直连 Dropbox 共享页的 TLS/共享页处理没有成功；同一批核心材料已经由 `github/iddqd` 和 `github/wulfic-liber-primus/reference/LiberPrimus.pdf` 覆盖。`reference/dropbox-link-error.html` 是第一次尝试时误用相似字符得到的 Dropbox 错误页，仅作诊断记录，不能当作 LP 材料。

## 暂未下载

- `The-Complete-Cicada3301-Archive` 的 GitHub 仓库约 476 MB，内容与现有原始档案有较大重叠；需要完整历史档案时再单独拉取。
- 截图中的 Google Colab 链接在图片中无法无歧义辨认出完整 Drive ID，因此没有猜测地址。当前两个可运行/可研究的代码库已经落地。
- YouTube 视频、Google Drive 书籍合集和论坛/Discord 私有内容只保留链接，不自动下载；需要时按版权和授权逐项处理。
