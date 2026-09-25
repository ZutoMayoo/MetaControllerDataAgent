# M13：Spider 2.0-DBT 统一证据适配器记录

## 结论

S-M1 已完成。DataLoom 现在可以通过统一能力路由调用固定版本的 SignalPilot 扫描实现，把 Spider2.0-DBT 的公开 instruction 与项目结构转换为确定性的 `DbtEvidencePackage dbt-0.1`。

本里程碑没有调用 Qwen，没有读取 Gold、历史评分或 evaluator，也没有修改三个任务项目。输出只包含公开 instruction、项目结构证据、来源定位和哈希。

## 为什么使用 dbt 专用合同

Code-aware `EvidencePackage 0.2` 的核心含义是“生产代码中的决策实现”，并要求完整的决策谓词和边界行为。dbt 项目扫描得到的是模型状态、列合同、依赖、source、macro 和日期风险。强行共用同一个规则结构会把项目结构错误标注为业务决策证据。

因此本轮保留统一的 DataLoom 能力路由、任务编号、producer、来源哈希和 artifact 哈希，但增加 `DbtEvidencePackage dbt-0.1` 专用载荷。两种合同职责不同，现有 Code-aware 质量门禁没有放宽。

## 能力与边界

- 复用固定 SignalPilot `scan_project.py` 的解析和分类函数，不复制其业务判断。
- 运行前校验扫描器 SHA-256；不匹配时失败关闭。
- 区分 `missing`、`stubs`、`complete` 与 `orphans`，避免把“有 SQL 文件”和“YML 声明且完整”混为一谈。
- 保存模型 required columns、description、materialization、ref 依赖、sources、macros 和 current-date hazards。
- 每条结构证据绑定项目相对路径、精确行号和文件 SHA-256。
- 保存公开 instruction 哈希、项目整体摘要哈希、完整文件清单哈希和证据包 artifact SHA-256。
- 包生成后立即执行独立校验；来源文件、instruction 或包内容被修改后校验失败。

统一编排新增动作 `spider2-dbt.evidence`，命令行入口为 `evidence-dbt`。

## 三题 Pilot 结果

| 任务 | missing | stubs | complete（YML 内） | orphan SQL | dependencies | sources | macros | 项目文件 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `playbook001` | 1 | 0 | 0 | 1 | 0 | 1 | 0 | 6 |
| `provider001` | 2 | 0 | 2 | 0 | 1 | 1 | 1 | 8 |
| `asset001` | 4 | 4 | 1 | 6 | 4 | 1 | 0 | 12 |

三题均无静态 current-date hazard。证据包分别保存到：

- `runs/spider2-dbt/sm1/playbook001.evidence.json`
- `runs/spider2-dbt/sm1/provider001.evidence.json`
- `runs/spider2-dbt/sm1/asset001.evidence.json`

## 验证

- DataLoom 全量测试：39/39 通过。
- 三个真实 Pilot 的证据包均在生成阶段通过来源和 artifact 校验。
- JSON 登记表与所有证据文件可正常解析。
- `git diff --check` 通过。

测试中的 pytest cache 警告来自 Windows 沙箱拒绝创建 `.pytest_cache`，不影响测试执行或结果。

## 下一里程碑

S-M2 的前置步骤是实现并审计 S0-S3 条件隔离：显式控制 structured evidence 和 dbt Skill 两个因素，运行记录必须保存实际注入的证据包 SHA-256、Skill 清单及 SHA-256。只有条件隔离测试通过后，才会调用 Qwen 对三个 Pilot 做端到端推理，并在候选冻结后由宿主评分。

## 文件明细

- 新增 `runtime/dbt_evidence.py`：dbt-0.1 生成与校验。
- 修改 `runtime/external_adapters.py`：SignalPilot 适配器新增证据包接口。
- 修改 `runtime/orchestrator.py`：新增统一 action 与 CLI。
- 修改 `runtime/test_reusable_adapters.py`：增加证据生成、篡改拒绝与能力暴露测试。
- 修改 `contracts.schema.json`：登记 `DbtEvidencePackage`。
- 修改 `实验注册表.json`：登记 S-M1 完成状态与产物位置。
- 新增三个 `runs/spider2-dbt/sm1/*.evidence.json` 真实 Pilot 证据包。
