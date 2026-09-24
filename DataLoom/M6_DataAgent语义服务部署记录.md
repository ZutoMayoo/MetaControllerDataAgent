# M6 External DataAgent 语义服务部署记录

日期：2026-09-24  
External DataAgent revision：`8208e7cbbc0c3351c76a4c292737ca05ab92cb4f`

## 结论

External DataAgent 的本地语义基础设施已经部署并通过可用性验证：

- PostgreSQL 16 + pgvector 使用独立 Docker 容器运行；
- Semantic Layer 0.1.0 使用 Java 21 运行；
- `BAAI/bge-base-zh-v1.5` 从本地 D 盘加载成功；
- 语义服务健康检查返回 HTTP 200；
- 40 张语义层表和 11 个检索工具完成初始化。

这完成了 BIRD 语义预处理的基础服务部署，但不等于正式 BIRD 推理已经
解锁。Qwen 隧道、BIRD train cache 和严格 Gold 隔离仍是后续门禁。

## 运行时隔离

所有第三方二进制、模型和运行数据均位于 Git 仓库之外：

`D:\GraduationProject\ProgressReport\runtime-assets\DataAgent`

主要运行时资产：

- `downloads/semantic-layer-0.1.0.tar.gz`
- `downloads/bge-base-zh-v1.5.tar.gz`
- `semantic/semantic-layer-0.1.0/`
- `models/bge-base-zh-v1.5/`

本阶段核验时运行时资产总占用约 1.42 GiB。P12 与 External DataAgent 两个
Git 工作区均无未提交改动。

## 完整性记录

| 资产 | SHA-256 |
| --- | --- |
| Semantic Layer 0.1.0 | `06F925A4BC1B2F70FCCC68AF67FD8ABF8D0FA92647213E3EE941951B21450812` |
| BGE base zh v1.5 | `2CA64FF541BE562D131207625D3B8866B837D3AD3C7C58C6B2127804B4C925B8` |

两个归档在解压前均检查了绝对路径和 `..` 路径穿越项，检查结果为 0。

## 服务配置

- Semantic Service：`127.0.0.1:32000`
- PostgreSQL：`127.0.0.1:54321`
- PostgreSQL 容器：`dataloom-semantic-pg`
- PostgreSQL 持久卷：`dataloom-semantic-pg-data`
- 业务 MySQL source：禁用
- 向量模型：本地 `bge-base-zh-v1.5`，768 维
- 语义编排模型：`qwen3.8-27b`
- LLM endpoint：`http://127.0.0.1:18020/v1/chat/completions`

PostgreSQL 仅绑定到本机回环地址；没有停止、重启或改写现有 Code-aware
容器。

## 验证证据

健康检查：

`GET http://127.0.0.1:32000/api/semantic/v1/types/typedefs`

结果：HTTP 200，响应包含语义边类型和节点类型定义。

启动日志关键证据：

- `Model loaded OK: BAAI/bge-base-zh-v1.5`
- `Semantic layer schema loaded from PG: 40 tables`
- `DjlEmbeddingProvider initialized, available models: [BGE_ZH]`
- `ToolRegistry initialized with 11 tools`

## 已识别的剩余门禁

1. 服务器重启后 Qwen SSH 隧道尚未恢复，暂不能执行列描述生成；
2. 官方/可信来源的 `train_cache.json` 尚未找到，不能伪造 SQL few-shot；
3. External DataAgent 上游 BIRD runner 仍会在推理进程内写入当前题 Gold，
   正式推理必须等待 sanitized bundle、隔离容器与 host-only evaluation 落地；
4. 当前评测题及其 Gold 禁止导入 semantic-service 的 few-shot namespace。

## 下一步

1. 恢复并验证 `18020 -> node3:8899` Qwen 隧道；
2. 确认可信 BIRD train cache 来源；
3. 先对单个数据库生成 description、OSI 并导入隔离 namespace；
4. 完成 Gold-safe 三段式执行器后再运行一题 canary。

## 本阶段文件变化

新增：

- `M6_DataAgent语义服务部署记录.md`

运行时目录中的第三方包、模型、日志和配置不纳入 Git。
