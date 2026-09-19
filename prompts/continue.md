先读 AGENTS.md 和精简 STATE.md。根据本次问题用 scripts/research.py find 定位，只读相关规范及1–2份审阅；需要验证才读取指定运行的record及直接证据。
不通读全仓库、不遍历所有旧运行、不默认恢复历史暂停任务。STATE_HISTORY.md和hypotheses/NEXT_HISTORY.md仅用于明确的历史追溯。
先指出上次实际结论及覆盖边界，再选择一个尚未覆盖的有界实验。
必要数据先核对 SHA-256 和来源；冻结评分器、参数、成功/失败标准。
运行后保留原始输出、命令、代码快照、种子、退出码和实际覆盖范围。
将 passed、negative、error、timeout、inconclusive 分开，更新简短 STATE.md 和下一步；详情写入 reviews/，不要继续将整篇历史报告堆入STATE。
不重复搜集故事、不润色候选当明文、不做未注册的大规模搜索、不创建定时任务。
