# M14：Spider 2.0-DBT 条件隔离与 Pilot 结果

## 结论

S-M2 已完成：三个冻结任务、四个条件共 12 条正式运行全部结束。候选均在容器内冻结并计算 SHA-256，之后才由宿主 evaluator 评分；正式结果为 2/12 PASS。

本轮证明了条件隔离与 Gold 安全评分链路可运行，但没有证明 evidence 或通用 dbt Skills 能稳定提升任务成功率。主要失败模式不是 SQL 语法错误，而是 Qwen 长时间停留在数据库探索，未进入文件修改与验证阶段。

## 条件隔离

所有条件均禁用动态 Skill 工具，避免自动发现污染。S2/S3 只由宿主静态注入固定并哈希的 `dbt-workflow`、`dbt-write`、`duckdb-sql`；S1/S2 只读挂载任务 evidence。

12 条运行记录中的实际观测与设计一致：S0 无 evidence/Skills，S1 仅 evidence，S2 同时具有 evidence/Skills，S3 仅 Skills。每题每条件均保存独立 manifest、准备审计、冻结候选和评分结果。

## Gold 泄漏修复

最初的 `playbook001 × S0` 直接复制原始 DuckDB，其中已经存在 evaluator 目标 View `attribution_touches`，该结果作废并记录在 `runs/spider2-dbt/sm2/invalidated/playbook001-S0-initial.json`。

正式运行统一经过 `prepare_spider_pilot.py`：根据宿主侧官方评测配置，从任务副本中删除目标 relation，并把审计文件留在宿主侧，不向 Agent 暴露。有效的 `playbook001 × S0-r3` 推理前仅保留 `ad_spend`、`customer_conversions`、`sessions`，因此其 PASS 有效。

## 正式结果

| 任务 | 条件 | 结果 | 回合 | 秒 | 终止状态 | 候选改动 |
| --- | --- | --- | ---: | ---: | --- | --- |
| playbook001 | S0-r3 | PASS | 13 | 39.4 | completed | 创建 `models/cpa_and_roas.sql` |
| playbook001 | S1-r1 | FAIL | 18 | 35.2 | repetitive_tool_loop | 无 |
| playbook001 | S2-r1 | PASS | 25 | 68.9 | completed | 创建 `models/cpa_and_roas.sql` |
| playbook001 | S3-r1 | FAIL | 26 | 111.2 | repetitive_tool_loop | 无 |
| provider001 | S0-r1 | FAIL | 19 | 58.9 | repetitive_tool_loop | 无 |
| provider001 | S1-r1 | FAIL | 52 | 318.3 | repetitive_tool_loop | 无 |
| provider001 | S2-r1 | FAIL | 26 | 217.4 | repetitive_tool_loop | 无 |
| provider001 | S3-r1 | FAIL | 78 | 1805.5 | budget_exhausted | 无 |
| asset001 | S0-r1 | FAIL | 27 | 65.8 | repetitive_tool_loop | 无 |
| asset001 | S1-r1 | FAIL | 14 | 57.1 | repetitive_tool_loop | 无 |
| asset001 | S2-r1 | FAIL | 25 | 76.5 | repetitive_tool_loop | 无 |
| asset001 | S3-r1 | FAIL | 25 | 58.9 | repetitive_tool_loop | 无 |

按条件计算，S0 为 1/3，S1 为 0/3，S2 为 1/3，S3 为 0/3。样本只有三题，不能据此声称因素存在统计显著增益；当前只能得出工程结论：S2 在简单单模型任务可完成，但复杂任务的控制策略仍是瓶颈。

## 失败分析

- 10 个失败候选全部没有文件改动；失败发生在“探索→实现”的阶段切换之前。
- 9 个失败由完全相同工具调用重复而熔断。
- `provider001 × S3` 的 SQL 文本持续变化，但语义上始终在枚举同一类字段组合，因此现有精确调用指纹无法识别，最终耗尽 1800 秒。
- evidence 能暴露缺失模型、依赖和列合同，但当前提示与控制器没有把这些证据转换成强制的实施计划和写入检查点。
- 通用 dbt Skills 提供方法知识，但没有针对单题约束探索预算，也没有保证 Agent 在限定回合内写入最小候选。

## 下一步门禁

暂不扩大 Spider2.0-DBT 样本。先实现 S-M3 控制器回归：增加语义循环识别、探索预算、强制实施检查点和“先写最小候选再验证”的阶段协议。使用同一三题回归，要求至少消除无写入超时，并确认没有引入草率写入、Gold 泄漏或条件污染，再决定是否扩样。

## 文件明细

- 新增 `runtime/spider_conditions.py`：S0-S3 条件合同、静态 Skill 注入与审计。
- 新增 `runtime/run_spider_pilot_agent.py`：容器内 Qwen runner、候选冻结和循环熔断。
- 新增 `runtime/prepare_spider_pilot.py`：任务副本准备与目标 relation 清除。
- 新增 `runtime/evaluate_spider_candidate.py`：冻结候选哈希校验与宿主评分。
- 新增 `runtime/run_spider_pilot_host.py`：单条正式运行编排。
- 新增 `runtime/test_spider_conditions.py`：条件隔离回归测试。
- 新增 `runs/spider2-dbt/sm2/`：12 份 manifest、正式运行副本、准备审计、候选和评分结果，以及 1 份作废结果记录。
- 修改 `实验注册表.json`：登记 S-M2 完成状态、结果和下一门禁。
- 新增本记录 `M14_Spider2_DBT_条件隔离与Pilot结果.md`。
