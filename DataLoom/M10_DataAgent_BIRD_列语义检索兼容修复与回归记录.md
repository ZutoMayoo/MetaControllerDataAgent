# M10：DataAgent BIRD 列语义检索兼容修复与回归记录

## 结论

Semantic Layer 0.1.0 的 `semantic-search-columns` 空指针问题已通过元数据兼容回填修复。相同的 Gold-safe、零 SQL few-shot BIRD canary 回归再次得到 `correct=true`。

## 根因

反编译并核对 Semantic Layer 0.1.0 的 `AdvancedSearchService.searchColumnName` 后确认，服务会对以下列属性直接调用 `toString()`：

- `column_name_desc`
- `column_description`
- `column_name_en`
- `db_name_en`
- `table_name_en`

本次 OSI importer 已导入其余字段，但 `column_name_desc` 为 null，因此向量检索命中实体后，在组装响应时触发空指针并返回 HTTP 400。

## 修复

扩展已有公共 API 回填脚本：更新 `data_column` 时，将现有安全的 `column_description_short` 同步写入：

- `columnDescriptionShort`
- `columnDescription`
- `columnNameDesc`

修复没有修改 Semantic Layer 二进制，没有直接写 PostgreSQL/pgvector，也没有引入 Gold、训练 SQL或模型猜测内容。

运行时审计报告（不纳入 Git）：

`runtime-assets/DataAgent/bird-semantic-no-fewshot/logs/debit_card_specializing_column_name_desc_repair.json`

## 接口级验证

使用 M9 中相同的 7 个关键词调用：

`advanced-search/semantic-search-columns`

结果：

- HTTP 400 → HTTP 200
- 返回 7 组关键词结果
- `Currency` 关键词首位召回 `customers.Currency`
- 该结果 score：2.0

## 隔离回归

- 任务：`debit_card_specializing` / question 1471
- 模型：`qwen3.8-27b`
- SQL few-shot：未使用
- `icl_top_k`：0
- Gold：仅在容器退出、candidate 哈希冻结后由宿主读取
- semantic-search-columns：2/2 请求成功，均为 HTTP 200
- 推理耗时：约 163.4 秒
- candidate SHA-256：`31c7e6f6cce131781bf70f23081a4e9e8fbc76f064d6b57bda756f23edfa420a`
- 宿主执行结果集评分：`correct=true`

最终候选：

```sql
SELECT CAST(COUNT(CASE WHEN Currency = 'EUR' THEN 1 END) AS REAL)
       / COUNT(CASE WHEN Currency = 'CZK' THEN 1 END)
FROM customers
```

成功运行目录（不纳入 Git）：

`runtime-assets/DataAgent/gold-safe-canary/q1471/run-m10-semantic-search-repaired-20260925`

## 回归测试

离线测试：35/35 PASS。

## 新增或修改文件

- 修改 `DataLoom/runtime/semantic_vector_backfill.py`
- 修改 `DataLoom/runtime/test_semantic_vector_backfill.py`
- 新增本记录

## 下一步

单题技术链路已经闭环。下一阶段应选择至少三个覆盖不同 SQL 结构的 BIRD 任务，分别包含单表聚合、多表 JOIN 和时间/分组逻辑，生成各自独立 namespace 与 Gold-safe bundle 后运行小规模能力回归。任务选择必须先基于公开问题字段完成，不能参考 Gold SQL 进行挑题。
