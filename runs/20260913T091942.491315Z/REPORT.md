# H000-v1 实际实验记录

状态：**passed**；所有命令退出码 0；已结束。完整机器记录见本目录 `record.json`。

| 字段 | 本次内容 |
|---|---|
| 假设 | 57 页恒等变换、56 页 prime-minus-one 加来源指定跳位可精确复现；小范围盲搜索可恢复合成同族密文 |
| 依据 | pinned QuickStart、iBot 73/74.md 及审阅过但未执行的素数变换 PHP、iddqd 原图/转写 |
| 数据版本 | sources/manifest.json + context-manifest.json 的 18 个文件 SHA-256；派生数据和训练/保留文本哈希详见 record.json |
| 上游版本 | iBot 63503b91b659179df18112b6d366b34dc61cbcb7；iddqd 0e3789ad2949c62ea7fb9e3e00ded93df3b3ce07 |
| 参数范围 | 56: offset=0, shift=1, skip rune ordinal 56、不消费流；57: identity；合成 offset=0..31, shift=0..28、无跳位 |
| 评分器 | 冻结训练词频 +1 平滑的对数似然和；不读取保留文本；固定排序和参数范围 |
| 成功标准 | 两页全部符文与独立预期一致、逆变换一致；三个合成挑战全部精确恢复密钥与 1196 符文 |
| 失败标准 | 已完成搜索选错答案为该基准的 negative；报错和超时另记，未覆盖不能排除假设 |
| 代码版本 | ac0370866db278a280fe36dbcd2bc9ae3e4e1c4908b735766ced8815c7ae1571（路径及文件 SHA-256 清单见 record） |
| 复跑包 SHA-256 | f73be238d3a8f7b8187fa2693ef674d21d501d1c214488bedd731a276e484485 |
| 实际覆盖 | 2 个已知页 / 180 符文；3×928=2784 个合成候选；未解页候选 0 |
| 原始输出 | tests.stdout/stderr.txt；reproduce/lp2_56/57.json、.txt；synthetic/trial-*/stdout.json、stderr.txt、verification.json |
| 下一步 | H001 跳位时钟语义；H002 行/段/散列边界时钟；H003 短文本正负对照校准，详见 hypotheses/NEXT.md |

实际入口命令（Windows Python 3.12.8）：

```powershell
python -X utf8 scripts/run_round.py
```

入口实际依次执行以下三个程序，绝对解释器/输出路径、起止时间和完整 stdout/stderr 已写入 record.json：

```powershell
python -X utf8 -m unittest discover -s tests -v
python -X utf8 scripts/reproduce.py --out runs/20260913T091942.491315Z/reproduce
python -X utf8 scripts/synthetic_benchmark.py --out runs/20260913T091942.491315Z/synthetic
```

随机生成种子（仅生成/验证端持有，搜索 stdin 中没有）：

1. 240692519862692216701831808073292188898
2. 245967838476668782194033710195591011479
3. 236395278571984787698281789880847519558

结果：18 项测试通过；56 页 85/85、57 页 95/95；56 页无跳位对照 29 个不匹配，首个在 ordinal 56；
三个合成挑战均精确恢复密钥及全部符文，每次 928 个候选、文件读取限制探针通过。
预期文本由验证模块读取，不进入解密器或盲搜索器；没有通过硬编码公开明文构造解密输出。

后续复跑检查：解压包中的完整闭环通过；用这些种子重建的三个 worker stdout 与原运行逐字节相同；
重建两页派生数据也逐字节相同。详见 `reviews/bundle-verification.json`。

解释边界：同一篇长保留文本的三个随机密钥，不是三个独立文本样本；无跳位小密钥空间不是未知 LP2 密码的代表性证明。
反向一致并非充分证据；本次还使用了来源参考精确验收及封闭答案验证。此结果不宣称发现任何新的未解页明文。
