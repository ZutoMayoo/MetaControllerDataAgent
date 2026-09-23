# M5 External DataAgent BIRD Gold 隔离与语义资产审计

日期：2026-09-23  
External DataAgent revision：`8208e7cbbc0c3351c76a4c292737ca05ab92cb4f`

## 结论

External DataAgent BIRD Suite 当前满足“模型调用参数中没有直接传入 Gold
SQL”，但不满足 DataLoom 的严格 Gold 物理隔离标准。因此：

- `--help`、probe 和 dry-run 可以继续使用；
- 正式 BIRD inference 必须阻断；
- 在拆分 inference 与 host evaluation 前，不启动真实模型请求。

## 数据流审计

推理角色实际收到：

- `question`：作为 `agent.chat()` message；
- `evidence`：放入初始 Bird state；
- SQLite snapshot：只读查询；
- semantic-service 返回的 schema、列值、JOIN 和 few-shot 信息。

当前代码没有把当前题的 `item["SQL"]` 直接放入 Bird state 或 LLM prompt。
但同一进程在调用 `agent.chat()` 前执行了以下操作：

1. 将 `item["SQL"]` 写入 case 目录的 `gold.sql`；
2. 将含 `SQL` 字段的完整 item 写入 `question.json`；
3. 父进程把含 Gold 的完整 questions 列表写入 worker JSON；
4. 推理完成后，同一 worker 进程执行 Gold SQL 并评分。

这意味着 Gold 虽未出现在正常 prompt 拼装路径里，但它在推理进程和推理
时段内已经存在。按 DataLoom 的威胁模型，应判定为 `BLOCKED`，而不是
“安全但暂未验证”。

## 已落地的强制门禁

`DataAgentBirdAdapter.probe()` 现在包含 `gold_isolation`：

- `status: BLOCKED`
- `safe_for_live_inference: false`
- 逐项报告源码文件、行号和违规类型
- 指定修复要求：sanitized inference bundle + isolated process/container +
  host-only evaluation

DataLoom 当前只暴露 External DataAgent 的 dry-run action，没有暴露 live
run action。因此 import check 成功不会自动扩大为正式运行权限。

## 语义资产审计

本机当前状态：

- semantic-service 容器/进程：不存在；
- BIRD `descriptions/`：不存在；
- BIRD `osi/`：不存在；
- BIRD `import_responses/`：不存在；
- `train_cache.json`：不存在；
- P10 BIRD mini-dev SQLite、描述 CSV 和 `dev_tables.json`：存在。

External DataAgent 完整 BIRD 语义路径额外需要：

1. Java 21+；
2. semantic-layer 0.1.0 服务包；
3. PostgreSQL 13+/pgvector；
4. 完整模式所需的 BGE 模型（约 228 MB）；
5. BIRD train cache；
6. 用预处理模型生成列描述并导入隔离 namespace。

因此现有资产不能直接复用成 External DataAgent 的正式 BIRD 运行环境。

## 安全改造方案

正式 canary 前应新增三段式边界：

1. Host Preparation：只把 `question_id/db_id/question/evidence` 和只读 SQLite
   放入 inference bundle；当前题 Gold 不进入 bundle；
2. Isolated Inference：External DataAgent 在独立容器中运行，只挂载 sanitized
   bundle 和输出目录；P10 原始题集、Gold 和宿主评测代码不挂载；
3. Host Evaluation：容器退出并冻结 candidate hash 后，宿主机再读取原始 Gold
   执行评分。

semantic-service 也必须使用与评测题隔离的 namespace，且禁止把当前评测题
Gold 导入 SQL few-shot 索引。

## 本阶段文件变化

修改：

- `runtime/external_adapters.py`
- `runtime/test_reusable_adapters.py`

新增：

- `M5_DataAgent_BIRD_Gold隔离与语义资产审计.md`
