# 来源边界

`manifest.json` 固定本轮 13 个主要来源；`context-manifest.json` 固定 5 个历史/用户上下文来源。
第二轮 `clues-v1-manifest.json` 增加 11 个固定来源，包括第一条正式 feed 原文和 LP1 相关资料；累计 29 个。
第三轮 `feed002-manifest.json` 增加数学 feed 原文及其 3 个固定 GitHub 引用；累计 33 个。
其中 Wulfic 页码/已解标签只作为被引用说法，不替代本项目已核对的页码和回归状态。
各条目包含 URL、UTC 获取时间、上游 commit（无版本的网页为 null）、文件大小和 SHA-256。
获取时间对本地副本表示本次快照时间；历史下载只能确认旧清单声称的 2026-09-13，精确时刻未知。

- iBotPeaches 固定 `63503b91b659179df18112b6d366b34dc61cbcb7`。
- iddqd 本地 HEAD `0e3789ad2949c62ea7fb9e3e00ded93df3b3ce07`；本轮使用副本均有内容哈希。
- QuickStart 在线正文已读取；直接 Python HTTP 请求返回 403，保留已有 HTML 并明确标记来源，未伪造新下载时间或网页版本。
- `ibot/...GeneratePlaintextFromPrimeShiftedCipher.php` 仅审阅文本来理解跳位语义；没有运行 PHP 或其他下载代码。
- `context/legacy-*` 是已有文档的历史快照，里面关于下载仓库及进展的说法不自动成为当前事实。
- `context/user-layout-reference.png` 是用户提供的结构建议，附图中的文字不作为额外操作授权。

SHA-256 证明本地文件后续未变动，不证明历史真实性、PGP 身份、版权归属或不同仓库的独立来源。
本轮没有验证 3301 签名、暗网页面或其哈希目标，也没有执行书内的任何行动要求。
上游材料保留其来源和原有许可；项目不为第三方材料重新授权。iBot 原 LICENSE.md 原样保存。

新增资料应建新的版本化快照；`acquire_sources.py` 和 `snapshot_context.py` 拒绝覆盖已完成快照。
通常复跑只运行离线闭环，不需要重新联网获取。
