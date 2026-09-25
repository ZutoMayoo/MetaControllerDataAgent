# M12：Spider 2.0-DBT 实验边界与 Pilot 冻结记录

## 结论

Spider 2.0-DBT 阶段的公开任务范围、Gold 边界、首批 pilot 和 S0-S3 对照条件已冻结，可以进入统一 dbt EvidencePackage 实现。

本里程碑只做公开输入盘点、只读项目扫描和环境检查，没有启动模型推理，没有修改任务项目，也没有读取 Gold 数据库或运行 evaluator。

## 数据与边界

- 公开任务索引：`P1/Spider-Agent-TC/Spider2/spider2-dbt/examples/spider2-dbt.jsonl`。
- 任务数：68；公开字段仅为 `instance_id`、`instruction`、`type`。
- 推理允许访问：单题 instruction、该题 dbt project、该题 DuckDB、固定版本工具与选定 Skill。
- 推理禁止访问：evaluation suite、Gold 数据库、历史评分、其他任务目录和旧候选。
- evaluator 只能在候选目录冻结并计算 SHA-256 后由宿主运行。
- P9 的 `PAID_API_DISABLED` 保持不变；本阶段不恢复旧的付费模型实验。

## S0-S3 操作定义

采用二因素 2×2 设计，两个因素分别是：

1. `structured_project_evidence`：SignalPilot 公开项目扫描结果转换成 DataLoom 结构化、可校验、可哈希的 dbt EvidencePackage；
2. `dbt_skills`：SignalPilot 的 dbt-workflow 及选定的数据库/领域 Skill。

| 条件 | structured project evidence | dbt skills | 目的 |
| --- | --- | --- | --- |
| S0 | 无 | 无 | 最小 Agent + 原始公开项目基线 |
| S1 | 有 | 无 | 单独测量结构化项目证据增益 |
| S2 | 有 | 有 | DataLoom 完整方案 |
| S3 | 无 | 有 | 单独测量 Skill 增益 |

当前 SignalPilot 默认会自动发现插件 Skill，因此不能直接把现有默认 runner 同时当作 S0 和 S3。S-M2 前必须增加显式条件开关，确保 S0/S1 禁用 dbt Skill、S2/S3 启用，并在运行记录中保存实际激活的 Skill 及 SHA-256。

四个条件固定使用同一任务副本、Qwen 模型、最大工具回合、超时、数据库快照和 evaluator。只有上述两个因素可以变化。

## 首批 Pilot

任务从公开索引与只读 SignalPilot 扫描结果中按结构选择，不参考 Gold SQL、Gold 数据库或历史得分。

| 任务 | 结构类型 | 公开结构摘要 | 项目规模 |
| --- | --- | --- | ---: |
| `playbook001` | 单个缺失模型 | 1 个缺失模型 `cpa_and_roas`；无 stub | 6 文件，1.02 MiB |
| `provider001` | 已有与缺失模型混合 | 2 个缺失模型；2 个完整模型 | 8 文件，22.53 MiB |
| `asset001` | 多模型联动 | 4 个缺失模型、4 个 stub、4 个完整模型 | 12 文件，44.52 MiB |

选择理由是覆盖由简到难的三种 dbt 改造形态，而不是追求已知容易题。pilot 只用于验证条件隔离、完成率和评分链路；通过后再冻结扩大样本。

## 复用组件与环境

- SignalPilot revision：`71dc57e4d915ebc2475d4cd27c6d5f8c405e5cf3`。
- `scan_project.py` SHA-256：`afd2657fbfd471cb652526a167dafc7476a0a32814381897970553ffa9a59ce4`。
- `validate_project.py` SHA-256：`ba5493a22fc69f56932077e7ffd83427a099f78a48b8d3ee33d927cf061e3ab5`。
- `dbt-workflow/SKILL.md` SHA-256：`53c21dfccc94ed46b5eccf695efd5061ec53a428167f2989778f449d357cd923`。
- 隔离镜像：`signalpilot-dbt-agent-clean:local`，ID `sha256:5714b00fc33ce99cac9ebba12cb44fcea52e49b5486d31373836c0b7f86c59bb`。
- 推理模型：服务器 `qwen3.8-27b`。
- OpenAI-compatible 隧道：`127.0.0.1:18020`，已验证。
- Anthropic 转换入口：`127.0.0.1:15721`，已验证。
- SignalPilot PostgreSQL 服务：已启动，服务名 `db`。

真实任务 `mrr001` 的只读扫描已经通过统一 DataLoom 路由成功运行，证明固定版本适配器能够处理实际 Spider dbt project。

## 已发现并修复的问题

统一编排入口在 Windows GBK 控制台输出扫描器的 `⚠` 字符时触发 `UnicodeEncodeError`。本轮将 CLI stdout 显式配置为 UTF-8，并增加回归测试。修复后真实任务扫描正常返回完整 JSON。

## 旧实验的使用规则

P9 已有实验是重要的工程与失败分析材料，但不能直接作为本轮正式 S0：

- 多个运行使用不同控制器版本；
- 部分结果是跨版本 carry-forward；
- 旧离线报告明确说明 13/68 不是单版本公平成绩；
- P8 的 51/68 使用不同模型与配置。

旧结果只用于风险清单：前置检查不能越权替 Agent 判断项目正确性，Verifier 证据不能由候选 SQL 自证，`INCONCLUSIVE` 不能简单当成错误。

## 下一里程碑

S-M1 将实现确定性的 dbt EvidencePackage 适配器：把公开扫描结果中的目标模型、缺失/stub 状态、依赖、列合同、source、macro 和日期风险转换成统一结构，同时绑定来源文件哈希。该阶段仍不调用模型和 evaluator。

## 文件明细

- 修改 `runtime/orchestrator.py`：Windows CLI 输出固定为 UTF-8。
- 修改 `runtime/test_reusable_adapters.py`：增加 UTF-8 输出配置测试。
- 修改 `实验注册表.json`：登记 Spider 设计、pilot 和当前状态。
- 新增 `M12_Spider2_DBT_实验边界与Pilot冻结记录.md`：本里程碑记录。
