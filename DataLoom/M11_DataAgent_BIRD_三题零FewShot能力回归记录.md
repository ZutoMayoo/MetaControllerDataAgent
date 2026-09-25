# M11：DataAgent BIRD 三题零 Few-shot 能力回归记录

## 结论

External DataAgent 在三个结构不同的 BIRD mini-dev 任务上全部完成推理，宿主执行评分为 3/3，Execution Accuracy 为 100%。

本轮严格不使用 `train_cache.json`，三个推理容器均记录 `sql_few_shot_used=false`。Gold SQL 只在容器退出且候选文件及 SHA-256 冻结后，才由宿主评测器读取。

本结果是三题小样本能力回归，只证明当前链路可以覆盖单表聚合、多表 JOIN、时间/分组三类任务，不代表 BIRD 全量准确率。

## Gold-safe 选题

选题只读取公开的 `question_id`、`db_id`、`question` 和 `evidence`，没有查看 Gold SQL。

| 类别 | question_id | db_id | 公开问题 |
| --- | ---: | --- | --- |
| 单表聚合 | 195 | `toxicology` | What is the most common bond type? |
| 多表 JOIN | 5 | `california_schools` | How many schools with an average score in Math greater than 400 in the SAT test are exclusively virtual? |
| 时间/分组 | 1479 | `debit_card_specializing` | Which year recorded the most consumption of gas paid in CZK? |

## 语义资产

`debit_card_specializing` 复用 M8-M10 已验证资产；另外两个数据库复用 External DataAgent 的列描述生成器与 OSI 构建器。

| db_id | 表 | 列 | column values | JOIN 边 | 向量回填 | sql_process |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| `toxicology` | 4 | 11 | 1,067 | 9 | 4/4 表、11/11 列、1,067/1,067 值双向量完整 | 0 |
| `california_schools` | 3 | 89 | 3,807 | 4 | 3/3 表、89/89 列、3,807/3,807 值双向量完整 | 0 |
| `debit_card_specializing` | 5 | 21 | 61 | 已有资产 | M8-M10 已完成 | 0 |

资产构建显式使用 `train-cache-mode=none`，同时传入不存在的 train-cache 路径；生成日志确认两个新增 OSI 均为 `sql_processes=0`。

## 基础设施修复

M8 的向量回填脚本原先对每类实体只查询前 1,000 条。California 资产有 3,807 个 column values，直接使用会漏回填。

本轮为 `SemanticApi.entities` 增加 offset 分页和重复页保护：

- 每页最多 1,000 条，直到空页或不足一页；
- GUID 在同页或跨页重复时 fail closed，避免服务忽略 offset 后无限循环；
- 新增两项单元测试覆盖完整分页和重复页拒绝。

实际 dry-run 完整读取 1,067 与 3,807 个值，应用后两套 namespace 的向量完整率均为 100%。

## 推理与评分结果

| qid | completion | 推理耗时 | candidate SHA-256 | 宿主执行评分 | 语义接口错误 |
| ---: | --- | ---: | --- | --- | ---: |
| 195 | 完成 | 175.307 秒 | `2c768073b84ae56973f6c839c089de46dd146ce39ea5d4171db65550be87711b` | correct | 0 |
| 5 | 完成 | 419.650 秒 | `4d1dd48cee0924986fbdfc7515b21178f0f395ec79c359c764c3f92ddf379e03` | correct | 0 |
| 1479 | 完成 | 1,712.550 秒 | `22e837cd221bf8ce6a76117d8de4ccd4962a203ba187ca49495f3f12acf60446` | correct | 0 |

三个候选均无预测执行错误，Gold 执行也无错误。所有 `semantic-search-columns`、关系检索和值检索调用均返回 HTTP 200；日志扫描没有发现 HTTP 400/500、Traceback、ERROR 或 `agent_error`。

Gold-free bundle 哈希：

- q195：`5b4cbf2a7900ced4ee58d59b19d6dc4d6e3722881c4020eddf015ec81f5f36cf`
- q5：`ab1e1a8af5b3a6329d4b87a386d976947a9f8cce213866ebe876d70e1bd049d9`
- q1479：`c6b6f187a3a9e8d90f2789bdfe6d7127ea483c89954230a7922c45679ec38245`

## 观察与风险

1. q5 最终候选直接比较 TEXT 型 `AvgScrMath` 与数值 400。内部验证器已提示缺少显式数值转换；本题结果正确，但对其他数据分布存在泛化风险。
2. q1479 最终候选对 TEXT 型 `Consumption` 直接求和。本题结果正确，但类型处理仍不稳健。
3. q1479 因候选执行结果未快速形成一致意见，触发多轮补充生成，耗时约 28.5 分钟。正确性通过，但效率是下一阶段最明显的瓶颈。
4. 三题样本太小，不能据此声称整体 BIRD 性能达到 100%。

## 验证

- DataLoom 全量离线回归：37/37 PASS。
- 新增分页测试：完整读取 1,001 条；重复页 fail closed。
- 推理模型：服务器 `qwen3.8-27b`。
- 镜像：`dataloom-dataagent-bird:9897a3b`。
- SQL few-shot：三题均未使用。
- Gold 边界：三题均在候选冻结后才由宿主评分。

## 文件明细

纳入 Git：

- `runtime/semantic_vector_backfill.py`：增加大规模实体分页与重复页保护。
- `runtime/test_semantic_vector_backfill.py`：增加两项分页回归测试。
- `M11_DataAgent_BIRD_三题零FewShot能力回归记录.md`：本里程碑记录。

不纳入 Git 的运行时产物：

- `runtime-assets/DataAgent/bird-semantic-no-fewshot/descriptions/`：新增两个描述缓存。
- `runtime-assets/DataAgent/bird-semantic-no-fewshot/osi/`：新增两个零 SQL-process OSI 文件。
- `runtime-assets/DataAgent/bird-semantic-no-fewshot/import_responses/`：新增两个导入响应。
- `runtime-assets/DataAgent/bird-semantic-no-fewshot/logs/`：新增 value stats、dry-run 和 apply 回填报告。
- `runtime-assets/DataAgent/gold-safe-canary/q5/`、`q195/`、`q1479/`：Gold-free bundle、推理候选、候选哈希、DataAgent 日志和宿主评分。

新增语义资产目录当前共 18 个文件、约 4.39 MiB；三个 bundle 还各自包含对应只读 SQLite 副本。

## 下一步建议

先做类型感知的候选约束与选择回归：当 SQLite schema 为 TEXT、但公开描述表明字段用于数值计算或比较时，要求候选显式 `CAST(... AS REAL)`，并让选择器优先保留类型安全候选。随后用当前三题做不降级回归，再扩展到 10-20 题的分层小样本。
