# M4 External DataAgent 隔离环境与 BIRD Dry-run 记录

日期：2026-09-23  
分支：`feat/production-evidence-gate`

## 目标

为从 GitCode 拉取的 External DataAgent 建立独立 Python 环境，并通过
DataLoom 统一编排入口完成 BIRD Suite 的导入检查和单题 dry-run。该阶段
不得启动正式推理，不得把 Gold 提供给模型。

## 环境

- External DataAgent revision：`8208e7cbbc0c3351c76a4c292737ca05ab92cb4f`
- Python：3.13.3
- 虚拟环境：`external/DataAgent/runtime/dataagent/.venv-dataloom-bird`
- 安装来源：External DataAgent 自带 `pyproject.toml`
- 安装范围：editable 基础包加 `nl2sql` extra
- `pip check`：`No broken requirements found`

虚拟环境由 `venv` 自带 `.gitignore` 排除，没有修改 External DataAgent 的
受版本控制源码。可使用 `DataLoom/scripts/setup_dataagent_bird_env.ps1`
重复创建和验收该环境。

## 验收结果

### 1. CLI import check

- `run_bird --help`：PASS
- DataLoom adapter 自动选择隔离环境：PASS
- adapter `isolated_environment`：`true`
- External DataAgent revision 和被调用文件 SHA-256：校验通过

### 2. 单题 dry-run

- 命令路径：DataLoom `orchestrator.py dry-run-bird`
- 数据：P10 BIRD mini-dev
- DB：`debit_card_specializing`
- question id：`1471`
- 模型配置：`qwen3.8-27b`
- 模式：`limited`
- preprocess：`skip`
- retry：关闭
- 选中题目：1
- worker：1
- LLM 并发预算：1
- 返回码：0
- 结果：PASS

Dry-run 只完成配置解析、题目选择和 worker 预算计算。没有请求 Qwen，
没有启动 semantic-service，没有生成 SQL，也没有创建所声明的正式 run
目录。

### 3. DataLoom 回归

- 离线测试：24/24 PASS

## 本阶段新增或修改

新增：

- `DataLoom/scripts/setup_dataagent_bird_env.ps1`
- `DataLoom/M4_DataAgent隔离环境与BIRD_DryRun记录.md`

修改：

- `runtime/external_adapters.py`：优先发现和使用隔离 Python 环境；probe
  报告是否处于隔离环境。
- `runtime/orchestrator.py`：新增结构化 `dry-run-bird` 命令。
- `runtime/test_reusable_adapters.py`：增加隔离环境选择断言。

不纳入 Git：

- `external/DataAgent/runtime/dataagent/.venv-dataloom-bird/`：本地可重建的
  第三方运行环境。

## 尚未授权为正式实验的事项

正式 BIRD 推理前仍需完成两项检查：

1. 审计 External DataAgent 的 BIRD case 构造，证明输入 JSON 中的 `SQL`
   Gold 字段不会进入 Agent prompt、tool observation、memory 或上下文转储；
2. 准备并只读验证 External DataAgent 所需的 semantic-service/OSI 资产。

在这两项完成前，不启动真实 BIRD 推理。
