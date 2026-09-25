# M9：DataAgent BIRD 零 Few-shot Gold-safe Canary 记录

## 结论

External DataAgent 在 BIRD `debit_card_specializing` 的 question 1471 上完成首个零 SQL few-shot、Gold 隔离 canary，宿主执行结果集评分为 `correct=true`。

推理容器退出并冻结 candidate 哈希之前，没有读取或挂载 Gold。Gold 仅在宿主评分阶段读取。

## 实验配置

- 模型：`qwen3.8-27b`
- bundle SHA-256：`f31962cd429c6cc6865856446e68ee087a393c14462656eea6f5c056acd7179c`
- 镜像：`dataloom-dataagent-bird:9897a3b`
- 镜像 ID：`sha256:d71a1d4245ba2e0188835bcd29822b3d69ce2ffa6c807b5e60a3fc6f2d64d6b9`
- Semantic namespace：`bird_dataloom_debit_card_specializing`
- `icl_top_k`：0
- 初始状态：`few_shot_examples=""`、`few_shot_lookup_complete=true`
- `sql_process`：0

## 执行过程

第一次启动在 DataAgent 模型初始化阶段失败：上游配置将 OpenAI-compatible Qwen endpoint 放在 `deepseek` provider 下，该版本读取 `DEEPSEEK_API_KEY`，原脚本只注入了 `LLM_API_KEY`。失败发生在模型调用前，没有生成 candidate，也没有进行评分。

修正后：

1. 隔离运行脚本同时注入占位的 `DEEPSEEK_API_KEY`；
2. 生成的 Agent 配置强制 `icl_top_k=0`；
3. 初始状态阻止 SQL few-shot 检索；
4. 重新构建不可变标签镜像；
5. 在全新的输出目录运行第二次 canary。

## 推理结果

推理耗时约 199.4 秒。DataAgent 生成 6 个可执行候选，最终冻结 SQL：

```sql
SELECT COUNT(CASE WHEN Currency = 'EUR' THEN 1 END) * 1.0
       / COUNT(CASE WHEN Currency = 'CZK' THEN 1 END)
FROM customers
```

candidate SHA-256：

`ac394af2cb90006b0dd07c7a09d00b507c748257270bfc98def5eb7a266c7ba0`

候选元数据明确记录：

- component：External DataAgent
- model：qwen3.8-27b
- `sql_few_shot_used=false`

## 宿主评分

- predicted row count：1
- Gold row count：1
- 结果集一致：是
- `correct=true`
- evaluation boundary：`host-only-after-frozen-candidate`

预测 SQL 与 Gold SQL 写法不同，但执行结果集一致，符合 BIRD execution accuracy 判定。

## 已观察问题

Semantic Layer 的 `advanced-search/semantic-search-columns` 两次返回 HTTP 400：

`Cannot invoke "Object.toString()" because the return value of "java.util.Map.get(Object)" is null`

DataAgent 自动降级为完整表结构、字段样例值和字段值向量检索。本题仍答对，因此该问题不是本题失败主因，但会削弱复杂多表题的列召回能力，需要在扩大样本前修复。

另一个观测项是 candidate 中 `llm_total_tokens=0`。模型调用实际成功，但当前上游 final state 未向 candidate 透传 token 统计；这不影响正确性，但影响成本与效率分析。

## 运行时产物

成功运行目录（不纳入 Git）：

`runtime-assets/DataAgent/gold-safe-canary/q1471/run-m9-zero-fewshot-20260925-r2`

关键文件：

- `inference/agent_config.yaml`
- `inference/candidate.json`
- `inference/candidate.sha256`
- `host-evaluation/host_evaluation.json`
- `dataagent_home/.../logs/main_*.log`

第一次失败目录原样保留用于故障审计：

`runtime-assets/DataAgent/gold-safe-canary/q1471/run-m9-zero-fewshot-20260925`

## 回归

本轮修改后离线测试：35/35 PASS。

## 下一步

先修复 `semantic-search-columns` 的空属性兼容问题，并新增接口级回归；修复后再运行多题 canary，以验证复杂题上的项目理解和 SQL 生成能力，而不是直接把单题正确率外推为整体能力。
