# M7 External DataAgent BIRD Gold 安全执行器记录

日期：2026-09-24
External DataAgent revision：`8208e7cbbc0c3351c76a4c292737ca05ab92cb4f`

## 结论

DataLoom 已实现独立于 External DataAgent 上游 evaluator 的三段式 BIRD
执行边界：

1. Host Preparation 只生成公开任务与只读 SQLite；
2. Isolated Inference 只挂载脱敏 bundle 和空输出目录；
3. Host Evaluation 仅在容器退出、candidate 哈希冻结后读取原始 Gold。

上游 runner 的三项 Gold 风险仍客观存在，因此 `DataAgentBirdAdapter` 不会把
上游 live run 标记为安全，也不会暴露该 action。DataLoom remediation 当前为
`READY_FOR_CANARY`，待完成一次真实 Qwen canary 后再决定是否开放新 action。

## 脱敏 bundle 合同

推理输入目录只允许三个文件：

- `manifest.json`
- `task.json`
- `database/database.sqlite`

`task.json` 只允许：

- `question_id`
- `db_id`
- `question`
- `evidence`

以下情况均 fail closed：额外文件、符号链接、额外字段、文件哈希变化、manifest
哈希变化、不可打开的 SQLite。

## 推理与评分边界

推理容器：

- 镜像：`dataloom-dataagent-bird:8208e7c`
- 镜像 ID：`sha256:4f1e4d6d94f0bea678c993f59a487e0ad16a647e261ffa4686996ebe2c3d0fd4`
- 镜像报告大小：860,809,583 bytes（约 821 MiB）
- External DataAgent 在镜像内安装并通过 import check；
- 容器根文件系统只读；
- drop all capabilities，启用 `no-new-privileges`；
- 输入 bind mount 为只读；
- 只允许独立输出目录为可写；
- 不挂载 P10 数据根、原始题集、Gold 或宿主 evaluator。

候选输出为 `candidate.json` 与 `candidate.sha256`。宿主评分前重新计算哈希，
并验证 candidate identity 与 bundle manifest。SQLite 以只读 URI 打开，同时
启用 `query_only` 和 authorizer，拒绝 INSERT、UPDATE、DELETE、ATTACH、DDL、
PRAGMA 与事务控制。

## 真实 mini-dev 预检

已对 `debit_card_specializing / question_id 1471` 生成脱敏 bundle：

`runtime-assets/DataAgent/gold-safe-canary/q1471/bundle`

bundle manifest SHA-256：

`f31962cd429c6cc6865856446e68ee087a393c14462656eea6f5c056acd7179c`

宿主审计和无网络只读容器内审计均返回 `safe: true`。该步骤没有调用 Qwen，
也没有执行或读取 Gold SQL。

## 回归结果

DataLoom runtime：29/29 PASS。

新增覆盖：

- bundle 只含公开字段和只读数据库；
- 额外 `gold.sql` 被拒绝；
- `task.json` 篡改被拒绝；
- candidate 哈希篡改被拒绝；
- candidate 数据库写操作被拒绝；
- 冻结 candidate 后 host-only evaluation 可正确评分。

## 剩余门禁

1. Qwen SSH 隧道尚未恢复，不能生成目标数据库的列描述；
2. `train_cache.json` 尚无可信来源，当前不能导入 SQL few-shot；
3. canary 所需语义 namespace 尚未生成和导入；
4. 在真实 Gold-safe canary 完成前，`safe_for_live_inference` 保持 false。

## 本阶段文件变化

新增：

- `runtime/bird_gold_safe.py`
- `runtime/test_bird_gold_safe.py`
- `docker/DataAgentBird.Dockerfile`
- `scripts/build_dataagent_bird_image.ps1`
- `scripts/run_dataagent_bird_isolated.ps1`
- `M7_DataAgent_BIRD_Gold安全执行器记录.md`

修改：

- `runtime/external_adapters.py`
- `runtime/test_reusable_adapters.py`
