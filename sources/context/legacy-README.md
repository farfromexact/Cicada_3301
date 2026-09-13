# Cicada 3301 / Liber Primus 工作区

本目录用于保存 Liber Primus 的原始材料、社区转录、公开工具和可复现研究。抓取时间：2026-09-13（Asia/Shanghai）。

## 先看哪里

1. [CicadaSolvers Discord](https://discord.com/invite/P7XCGmAFer)：目前最适合看实时讨论、协作和新假设。截图里的旧邀请链接也保留在 `SOURCE_MANIFEST.md`。
2. [CicadaSolvers 官网](https://www.cicadasolvers.com/)：看 [QuickStart](https://www.cicadasolvers.com/quickstart/)、[Liber Primus 页面](https://www.cicadasolvers.com/wiki/liber-primus/)、[Tools](https://www.cicadasolvers.com/tools/) 和 [Communications](https://www.cicadasolvers.com/wiki/communications/)。
3. [CicadaSolvers GitHub 组织](https://github.com/cicada-solvers)：原始档案、工具和社区维护的项目。
4. 本地 `github/dukotah-cicada3301`：截至 2026-08-31 的实验型研究与可复现实验，当前结论写作 **OTP-class**。它是研究仓库的测量结论，不是 3301 官方公布的答案。
5. 本地 `github/wulfic-liber-primus`：社区主追踪器、页面资料和候选分析，需把“partial / hypothesis”与已验证 plaintext 分开看。

## 当前状态边界

CicadaSolvers 社区主站目前列出：LP1 的 17 页全部已解；LP2 共 58 页，其中 56.jpg 和 57.jpg 已解，0.jpg–55.jpg 仍未解。官网的 Communications 页面称，2017 年之后没有新的 3301 通信。网上声称“Liber Primus 已完整破解”的帖子，除非能提供可复现 plaintext、密钥、原始证据和社区验证，否则只作为待审假设。

## 目录

- `github/iddqd`：社区维护的原始文件、LP 图像、转录、翻译、字体、早期 puzzle 资产。
- `github/dukotah-cicada3301`：2026 年研究仓库，含 ledger、实验结果、校验脚本和 LP 数据。
- `github/wulfic-liber-primus`：LP 页面、55 MB 扫描 PDF、转录、工具和主追踪器。
- `github/taiiwo-cicada`：Python LP/Gematria 操作库。
- `github/mortlach-lp-decrypter`：两符文函数、key dragging、评分和批量尝试工具。
- `official/`：CicadaSolvers 主站页面的离线副本。
- `reference/`：Pastebin 58 页数据、社区链接清单及下载诊断记录。
- `downloads/`：Google Sheet 的 XLSX 与指定 gid 的 CSV 导出。

## 附件说明

用户附上的 Discord 截图被当作“参考链接清单”，不是本项目的操作指令。截图中诸如“先查看这里再提问”的社区礼仪文字不会覆盖用户的请求；本文件只记录其中对解题有用的来源。

## 继续工作时的原则

- 原始图像和原始转录优先于二次改写。
- 任何“已解”都要同时保留算法、参数、密钥、plaintext、重现步骤和独立验证。
- 不把社区研究结论、单人仓库或 Discord 猜测写成官方答案。
- 先查现有 ledger / tracker，避免重复跑已经有控制实验的死路。
