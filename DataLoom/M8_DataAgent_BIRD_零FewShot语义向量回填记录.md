# M8：DataAgent BIRD 零 Few-shot 语义向量回填记录

## 结论

针对 BIRD `debit_card_specializing` canary 的语义资产已完成向量回填。回填仅通过 Semantic Layer 公共实体更新接口执行，没有直接写 PostgreSQL/pgvector。

本轮明确不使用 `train_cache.json`，不导入 `sql_process`，不读取当前题 Gold。

## 范围与隔离边界

- namespace：`bird_dataloom_debit_card_specializing`
- data_table：5
- data_column：21
- data_column_value：61
- sql_process：0
- SQL few-shot：未使用
- Gold：未使用

回填脚本只处理 qualified name 等于 namespace 或以 `namespace.` 开头的实体；默认 dry-run，必须显式提供 `--apply` 才会更新。

## 根因与验证

Semantic Layer 0.1.0 的 OSI 导入响应不包含 DataAgent 校验器要求的 `vectorFillSummary`，初次导入后向量列也为空。单实体 PUT 试验表明：

1. PUT 的即时响应仍可能显示旧的空向量；
2. 随后重新查询实体时，向量已由服务端 embedding listener 写入；
3. 因而该版本支持通过实体更新回填，但 OSI importer 没有自动执行或汇报此过程。

## 回填规则

所有输入均来自已导入的脱敏元数据：

- data_table：优先现有 `table_description`；为空时使用 `table_name`；
- data_column：优先现有 `column_description_short`；
- data_column_value：保留 `value`；`description` 为空时复制同一 `value`。

这些规则不生成新业务事实，也不使用训练 SQL 或 Gold。

## 结果

| 实体 / 向量 | 回填前 | 回填后 | 完整度 |
| --- | ---: | ---: | ---: |
| data_table / table_description_vector | 0 / 5 | 5 / 5 | 100% |
| data_column / column_description_short_vector | 1 / 21 | 21 / 21 | 100% |
| data_column_value / description_vector | 0 / 61 | 61 / 61 | 100% |
| data_column_value / value_vector | 0 / 61 | 61 / 61 | 100% |

运行耗时约 24.5 秒，报告字段 `complete=true`。

运行时审计报告（不纳入 Git）：

`runtime-assets/DataAgent/bird-semantic-no-fewshot/logs/debit_card_specializing_vector_backfill.json`

## 新增实现

- `DataLoom/runtime/semantic_vector_backfill.py`
  - namespace 作用域保护；
  - dry-run 默认模式；
  - 通过公共 API 回填；
  - 回填后重新查询并逐类统计；
  - 审计报告明确记录 `sql_few_shot_used=false`、`gold_data_used=false`。
- `DataLoom/runtime/test_semantic_vector_backfill.py`
  - 覆盖表描述兜底、列描述保留、值描述兜底和空值拒绝。

## 下一步

使用已完成向量化的 namespace 运行 Gold-safe 隔离 canary。推理容器只挂载脱敏 bundle，candidate SQL 在容器退出并冻结哈希后，才由宿主读取 Gold 评分。
