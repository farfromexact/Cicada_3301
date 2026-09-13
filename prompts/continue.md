读取 AGENTS.md、STATE.md、最新实验 record.json、reviews 和相关假设规范。
先指出上次实际结论及覆盖边界，再选择一个尚未覆盖的有界实验。
必要数据先核对 SHA-256 和来源；冻结评分器、参数、成功/失败标准。
运行后保留原始输出、命令、代码快照、种子、退出码和实际覆盖范围。
将 passed、negative、error、timeout、inconclusive 分开，更新 STATE.md 和下一步。
不重复搜集故事、不润色候选当明文、不做未注册的大规模搜索、不创建定时任务。
