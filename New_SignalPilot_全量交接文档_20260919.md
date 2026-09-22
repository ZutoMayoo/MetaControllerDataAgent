# New SignalPilot 全量交接文档

交接日期：2026-09-19  
工作区：`D:\GraduationProject\ProgressReport`  
本文件覆盖本对话中自 P10 技术规格审计开始，到 BIRD 轻量级 Mapper 实验完成为止的架构、代码、实验、运行环境与遗留事项。

## 0. 交接结论

当前可复用的核心成果是：

1. **BIRD New SignalPilot 已完成两类分层复测。** 对旧 PASS 群体的 50 题样本，获得 `47/50` PASS（94% 保留）；对旧 `NO_SQL` 群体的 50 题样本，获得 `22/50` PASS（44% 恢复）。据此对 500 题 BIRD-mini-dev 的保守外推为约 **64%**，不是完整全量成绩。
2. **BIRD Mapper 已由模型驱动、约束型角色改成确定性、事实型非阻塞上下文。** 它不再替 Executor 推断 SQL 的表、列、JOIN、COUNT 口径或输出格式。
3. **Spider 的 Preparation 已显著放宽并改为 source-only 工作库。** 已有 API-free dry-run 证据表明 67/67 个有效数据库任务可构建，公开 raw/source 输入没有缺失；但 Spider 正式全量实验存在多次宿主 runner 非正常中止，必须重新核验运行状态后再继续。
4. **不要把 Verifier 当作官方正确性裁判。** 当前它只应输出可审计证据和风险状态；官方宿主机评测才是正确性标准。

下一位 GPT 的优先任务应是：先读取本文件所列产物并确认代码哈希、隔离和环境，然后复测 BIRD 剩余 80 个“已有 SQL 但评测错误”的任务，或运行完整 500 题以确认约 64% 的外推；Spider 需要先解决宿主 runner 可靠收尾问题。

---

## 1. 项目结构与关键入口

| 组件 | 位置 | 用途 |
| --- | --- | --- |
| 原始 SignalPilot | `P4\SignalPilot` | 原始 SDK runner 及基线对照 |
| Spider New SignalPilot | `P9\optimizedAgent\clean_replay` | Spider2.0 Preparation、Agent、Repair、全量 runner |
| BIRD New SignalPilot | `P10\BIRD-MetaController` | BIRD 实验主目录、Docker runner、评测产物 |
| 规格与审计资料 | `P10\meta_controller_review_20260907` | P10 审计、修复方案和验收记录 |
| 本轮报告 | `P11` | 轻量 Mapper 实验工作报告与 PPT 提纲 |
| 本交接 | `P12\New_SignalPilot_全量交接文档_20260919.md` | 供后续 GPT 接手 |

BIRD 的关键代码：

- `P10\BIRD-MetaController\agent_entry.py`
- `P10\BIRD-MetaController\src\meta_controller.py`
- `P10\BIRD-MetaController\runtime\sdk_runner.py`
- `P10\BIRD-MetaController\scripts\run_canary_three.ps1`
- `P10\BIRD-MetaController\evaluate_canary.py`
- `P10\BIRD-MetaController\tests\test_offline_workflow.py`
- `P10\BIRD-MetaController\tests\test_qwen_runner_isolation.py`

Spider 的关键代码：

- `P9\optimizedAgent\clean_replay\prepare_task.py`
- `P9\optimizedAgent\clean_replay\preparation_contract.py`
- `P9\optimizedAgent\clean_replay\agent_entry.py`
- `P9\optimizedAgent\clean_replay\run_full_experiment.ps1`
- `P9\optimizedAgent\clean_replay\replay_failed.ps1`
- `P9\optimizedAgent\clean_replay\audit_preparation_contract_dry_run.py`
- `P9\optimizedAgent\clean_replay\audit_preparation_matrix.py`

---

## 2. P10 阶段的架构审计与可信离线核心

### 2.1 初始审计判断

P10 的技术规格与代码审计发现，原先“增加 Meta-controller”不能仅靠增添 Python 类完成。若候选库、冻结、阶段协议和生产 runner 没有贯通，所谓多阶段控制仍会退化为旧的单容器 `agent_entry.py` 流程。初始 75% 基线还受实验环境封闭不严格影响，后续统一以 **65% SOTA 基线**作为对照，不再使用 75%。

主要问题包括：

- Preparation 阶段误杀过多，特别是 YAML/Jinja 和任务文本无法正则提取模型名时；
- Verifier 的内部结论被误用为正确性判定，口径与官方评测不一致；
- 旧模型 Mapper 会提前做 SQL 决策，导致错误假设传递到 Executor；
- Docker/runner 的阶段化、mount 证据、resume 与故障恢复没有完全闭合；
- 在某些运行中，宿主 runner 在任务容器结束后、终态产物写入前中止，造成 manifest 假性 `RUNNING`。

### 2.2 M1：可信离线核心

M1 只构建离线可信原语，未改动生产 runner、未启动 Docker/模型/API。已有实现和验收记录在：

- `P10\meta_controller_review_20260907\W1_M1可信离线核心_实施记录_20260909.md`
- `P10\meta_controller_review_20260907\W1_M1局部修复_验收报告_20260909.md`
- `P10\meta_controller_review_20260907\W1_M1局部修复_独立复审报告_20260909.md`

其内容包括：

- 严格 `CandidateRef v3`、独立候选快照、宿主机冻结 C1；
- 首事件为 `FROZEN` 的加锁 lifecycle 哈希链；
- 严格 phase protocol；fake 与生产入口分离，生产入口不伪造 PASS；
- Host Supervisor 的 C0/C1 安全选择、幂等 resume 与发布窗口 reconcile；
- baseline/release manifest 分离；
- 严格 manifest schema、重复 JSON key 拒绝、候选与 validation/lifecycle 绑定。

该部分有定向 API-free 测试通过记录，但**不应据此宣称 W1 的真实 Docker 四容器生产迁移已经完成**。M2（真实 runner 的四阶段迁移、mount inspect/mountinfo 证据、fault injection、完整 resume）仍是独立未闭合工作。

---

## 3. Spider：Preparation 与 Verifier 口径改造

### 3.1 Preparation 的真实任务输入合同

修改方向不是让 Preparation 猜测 SQL 或评分标准，而是保证公开任务不会在进入 Agent 前被误杀。

已实施的原则：

- Preparation 只读取公开 instruction、SQL、YAML 和公开 source/schema 信息；不读取 `evaluation_suite/gold`、`condition_tabs` 或其他评分配置。
- YAML/Jinja 解析异常、公开语义未能精确抽取目标模型等，不再直接阻断；以 `DEFER_TO_MAPPER` 或诊断信息继续进入后续流程。
- Agent 不接触原始 DuckDB。`preparation_contract.py` 从原库构造 source-only 工作库，再写入任务工作区。
- 公开 source identity 优先于 model identity。source/model 同名时保留 source relation；source view 可从只读原库物化。
- 派生 relation 只在有公开项目证据时进入 denylist；不按 view 类型或 YAML `refs` 无条件删除。
- 工作库构建使用临时文件、失败清理与原子发布；保留 schema、行数和逻辑摘要证据。

### 3.2 API-free 验收记录

相关产物：

- `P10\meta_controller_review_20260907\preparation_contract_dry_run_final_after_audit_fix2_20260910.json`
- `P10\meta_controller_review_20260907\denylist_input_conflicts_after_fix_20260910.json`
- `P10\meta_controller_review_20260907\Preparation最新修复独立审计_20260910.md`

已报告的 dry-run 结果：

| 项目 | 结果 |
| --- | ---: |
| 有效数据库任务可构建 | 67/67 |
| `gitcoin001` | 唯一 `BLOCKED_TASK_INPUT` |
| raw/source 缺失 | 0 |
| 原始数据库 Hash 改变 | 0 |
| 双构建逻辑摘要差异 | 0 |
| 确定派生缓存删除 | 23 |
| source/model 同名而保留 | 5 |
| 未分类 base table 保留 | 1443 |

这些结果说明 Preparation “过严”的主要路径已被放宽；但继续修改前应先重新运行 current-code 的矩阵与生产 Prepare 接入检查，避免把旧 dry-run 误当成当前生产验收。

### 3.3 Verifier 的正确定位

Verifier 已改为输出结构化、可审计的证据性状态，例如：

- `SCALAR_EQ_ZERO`、`SCALAR_GT_ZERO`
- `PROJECTION_AMBIGUOUS`
- `COUNT_GRAIN_AMBIGUOUS`
- `JOIN_FANOUT`
- `OUTPUT_SHAPE_MISMATCH`

它具有查询预算与无工具 JSON finalizer。它可以发现候选 SQL 的内部不一致、连接膨胀或输出形状风险，但看不到官方答案，不能证明候选与官方 gold 相同。用户指定的探索性 Repair 规则是：若官方最终评测 FAIL 且 Verifier 状态明确需要修复，则回送 Repair Agent 一次；再次 FAIL 不进行第二次 Repair。后续接手者应先审计当前 `agent_entry.py` 是否仍完整保留这一调用链，再决定是否使用。

---

## 4. Spider：实验运行、故障与状态

### 4.1 本地 Qwen 预检

曾成功运行：

```powershell
& .\P9\optimizedAgent\clean_replay\run_full_experiment.ps1 `
  -Provider QwenCCSwitch `
  -Model qwen3.8-27b `
  -RunId qwen-repair-v1-preflight `
  -PreflightOnly
```

输出为 API-free controller tests `156`（后续版本 `157`）项通过，Container import smoke PASS，68 题 Preflight PASS，且预检不调用 API。

### 4.2 已出现的故障模式

1. **Mapper/Agent 循环。** `playbook001` 曾在重复工具调用中卡住，日志有持续 Heartbeat。已在 `P4\SignalPilot\benchmark\agent\sdk_runner.py` 增加重复工具调用指纹：连续 3 次 warning，第 4 次返回 `REPETITIVE_TOOL_LOOP`；仅默认用于 `SQL_EXECUTION` / `isolated-sql-executor`。`agent_entry.py` 对该状态保留有效候选并运行现有验证，不再一律转为 `PRIMARY_INCOMPLETE`。
2. **终态产物缺失。** 曾报 `ValueError: agent output has no terminal controller phase`，导致 `produced no hash-matched terminal artifact`，runner 停止调度。说明每一次容器结束后都必须验证宿主 terminal artifact，而不能只看容器日志。
3. **旧容器残留。** `Refusing to start while 1 replay container(s) are already running.` 表示 runner 检测到已有 replay container。必须先只读检查 Docker label/容器归属，不能误杀 BIRD 容器。
4. **manifest 假性 RUNNING。** 多个 `qwen-repair-v*` 运行在宿主机中止后留下 `RUNNING`。恢复前必须检查最新任务产物时间、`terminal.json`、关联 Docker 容器与宿主 launcher 进程，而不能仅信 manifest。

### 4.3 当前 Spider 状态

本对话后期用户要求暂停并删除后台 Spider 进程，重点转向 BIRD。不要假定 Spider 仍在运行。接手前请：

1. 查看 `P9\optimizedAgent\clean_replay\results` 或 run root 中的最新 manifest、terminal artifact 和 evaluator 输出；
2. 使用 Docker label 明确区分 Spider 与 BIRD 容器；
3. 若代码 Hash 与镜像设置不变，使用原 RunId 的 resume；若修改代码，使用新 RunId；
4. 只在当前 Preparation 合同和 runner 入口复审通过后，才重新启动 Spider 全量。

---

## 5. BIRD：环境与运行配置

### 5.1 服务器与 SSH 隧道

交接时远端 node3 曾监听 8888，但截至 2026-09-21 该端口已停止服务。当前 8899 与 8889 均可返回 `qwen3.8-27b`，统一固定 **8899 为主端口**、8889 为备用。此前使用 8020 会 `Connection refused`。建立隧道：

```powershell
ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 `
  -L 127.0.0.1:18020:127.0.0.1:8899 `
  -p 8803 chengyichao@115.236.33.122
```

隧道必须保持在独立 PowerShell 窗口中；关闭该窗口会使 BIRD/Spider 容器经本机兼容路由返回 502。

远端只读探测：

```bash
curl -sS --max-time 5 http://127.0.0.1:8899/v1/models
```

预期模型 id：`qwen3.8-27b`。远端共享 vLLM 由其他用户启动，常见参数为 Tensor Parallel 2、当前主端口 8899、`qwen3` reasoning parser、`qwen3_coder` tool-call parser；**不要在未获服务器所有者确认时停止或重启该共享服务**。

### 5.2 本地兼容路由

本机直连模型探测：

```powershell
curl.exe -sS --max-time 10 http://127.0.0.1:18020/v1/models
```

本地 Anthropic 兼容路由：`http://127.0.0.1:15721/v1/messages`。其 `/v1/models` 返回 `{"models":[]}` 是该兼容层的正常表现，不能据此判定路由故障；应使用一次无副作用的 `/v1/messages` 请求或容器日志确认。Docker 中的 endpoint 固定为：

`http://host.docker.internal:15721`

必要环境变量由 BIRD runner 注入：

- `ANTHROPIC_BASE_URL=http://host.docker.internal:15721`
- `ANTHROPIC_API_KEY=local-vllm-placeholder`
- `ANTHROPIC_AUTH_TOKEN=local-vllm-placeholder`
- 各默认 Anthropic 模型变量均为 `qwen3.8-27b`

`PAID_API_DISABLED` 标记保留在项目中。它用于防止意外落回付费供应商，并不禁止已明确配置的本地 Qwen 路由。

### 5.3 BIRD Docker 隔离

`scripts\run_canary_three.ps1` 对每题执行独立容器：

- 独立任务工作区：`results\<RunId>\work\bird-<id>`；
- 数据库使用每 Run 的 SQLite snapshot，以只读 mount 注入容器；
- Agent entry、query tool、`src`、本地 SDK 均以只读 mount 注入；
- 网络为 bridge，容器使用 `agentuser`，`cap-drop ALL`、`no-new-privileges`、`pids-limit 384`；
- BIRD 与 Spider 使用不同 workspace、标签、结果目录和本地 SDK 路径。

运行前要求 Docker Desktop 正常运行，机器不可睡眠，SSH 隧道不可关闭。

---

## 6. BIRD：运行命令与恢复规范

### 6.1 新运行

```powershell
& .\P10\BIRD-MetaController\scripts\run_canary_three.ps1 `
  -ConfirmRun `
  -RunId <新的合法RunId> `
  -Tasks "305,472,46" `
  -Model qwen3.8-27b
```

`-Tasks` 可替换为以逗号分隔的 BIRD task id。启动时 runner 会执行离线测试、检查 `PAID_API_DISABLED`、本地镜像、隔离数据库和代码 Hash。

### 6.2 恢复同一 RunId

只有以下条件同时满足时才 resume：代码 Hash、镜像、模型、Verifier 预算和任务集均未变，且不存在该 RunId 所属的活跃 BIRD 容器。

```powershell
& .\P10\BIRD-MetaController\scripts\run_canary_three.ps1 `
  -ConfirmRun -Resume `
  -RunId <旧RunId> `
  -Tasks "<必须与manifest完全相同的任务列表>" `
  -Model qwen3.8-27b `
  -MainTurns 70 -RoleTurns 35 -RepairTurns 40 `
  -VerifierQueryBudget 12 -VerifierFinalizerTurns 3
```

resume 的跳过依据是 `results\<RunId>\bird-<id>\terminal.json`。仅有 `candidate.sql` 或 `agent_output.json` 不算提交完成，会重放该题；其数据库 snapshot 是隔离的，因此可安全重放。

### 6.3 宿主 runner 可靠性教训

`bird-deterministic-context-oldpass50-v1` 两次出现“任务内部已有完整产物、宿主机却未写 `terminal.json`”的中止。表现为：

- `run_manifest.json` 仍为 `RUNNING`；
- `work\bird-<id>` 已有 `agent_output.json`、`candidate.sql`、`controller_trace.json`、`role_audit.json`；
- `results\bird-<id>` 没有 `terminal.json`；
- 后续题未被调度。

当时以同一 RunId resume 并跳过已提交任务，最终成功完成 50 题。一次临时 Windows Task Scheduler 托管尝试返回 code 1 且无日志，已被禁用；不要假设该任务可用。下次应优先修复 runner 的宿主 Supervisor/进程托管方式，例如将每题启动与 artifact 提交分离并写入原子 host state，而不是依赖 manifest `RUNNING`。

---

## 7. BIRD：轻量级 Mapper 改进

### 7.1 改造前

旧 Mapper 会调用模型，并试图预先决定模型/表/列/投影/COUNT/JOIN 等 SQL 设计。它可能：

- 为 Executor 注入错误约束；
- 消耗大量回合；
- 因工具循环、越界文件搜索或空 scope 使任务没有候选 SQL。

### 7.2 当前实现原则

`schema_context.json` 是确定性事实型上下文，包含：

- schema、字段类型、主键/外键；
- 描述文件清单；
- 题目文本和 schema 名称的词法匹配；
- 构造来源和版本。

它不推断投影列、`COUNT(*)` 与 `COUNT(DISTINCT)`、具体表选择、JOIN、排序或输出格式。Executor 自己查询数据库并生成 `candidate.sql`；上下文不能阻塞它。

附加保护：

- Executor 和 Verifier 有重复工具调用熔断；
- Verifier 有查询预算和强制 JSON 收尾；
- Agent 在可行时尽早写入 `candidate.sql`；
- 工具策略阻止越界操作，但应优先提供安全的只读数据库查询路径。

### 7.3 根因判断

Mapper 已被基本排除为当前低通过率的唯一主因。主要剩余问题：

1. Qwen 对自然语言隐藏评测口径的判断不稳定，例如 `COUNT(*)` / `COUNT(DISTINCT)`、`id` / `name`、`rank` / `position`、原始 ID / 描述文本；
2. 单候选路径无法覆盖合理的投影、聚合粒度和排序歧义；
3. Executor 仍可能过度探索，或在写入候选前因工具策略失败；
4. Verifier 能证明内部一致，不能获知官方 hidden gold；
5. Repair 若仅依赖 Verifier，无法稳定纠正“内部合理但不符合官方口径”的 SQL。

---

## 8. BIRD：实验记录与数据

### 8.1 原始全量基线

Run：`P10\BIRD-MetaController\results\bird-qwen-full-v1\evaluation.json`

- 500 题；
- 267 PASS，准确率 53.4%；
- 153 题状态为 `NO_SQL`；
- 其余 80 题为已生成候选但官方评测错误的其他失败。

### 8.2 归因对照

| 实验 | RunId | 结果 | 含义 |
| --- | --- | ---: | --- |
| 原始单 Agent 对照：346、397 | `bird-signalpilot-baseline-346-397-v1` | 0/2 | 这两个失败不能单独归因于 Mapper |
| 13 个疑似 Mapper 案例的原始单 Agent | `bird-signalpilot-baseline-mapper-cases-v1` | 2/13（15.38%） | Mapper 会放大部分失败，但其余 11 题单 Agent 也失败 |
| 轻量 Mapper：16、283 | `bird-light-mapper-16-283-v1` | 1/2 | 删除强约束后仍有 COUNT 口径问题 |
| 确定性上下文：16、283 | `bird-deterministic-context-16-283-v2` | 1/2 | 16：66→36 回合；283：59→34 回合 |

具体失败样例：

- 346：过滤逻辑正确但模型投影 `name`，官方要求 `id`；
- 397：输出第三列编码、`DISTINCT` 与连接粒度仍不符；
- 16：COUNT 口径不稳定；
- 283：确定性上下文后仍可 PASS。

### 8.3 旧 NO_SQL 分层样本

样本：

- `experiments\no_sql_sample_50_20260916.json`
- RunId：`bird-deterministic-context-nosql50-v1`
- 样本来自旧 `NO_SQL` 的 153 题，按 `(db_id, difficulty)` 比例分层。

结果：

| 指标 | 结果 |
| --- | ---: |
| 官方宿主机评测 PASS | 22/50 |
| 通过率 | 44% |
| 有效 SQL | 47/50（94%） |
| NO_SQL | 3/50 |
| 评测 SQL 超时 | 1 题（393） |

三个未生成 SQL 的典型原因：317 的 Executor/Repair 耗尽回合，382/495 尝试越界文件搜索而被工具策略拒绝。

### 8.4 旧 PASS 分层样本（已完成）

样本：

- `experiments\old_pass_sample_50_20260917.json`
- RunId：`bird-deterministic-context-oldpass50-v1`
- 结果：`results\bird-deterministic-context-oldpass50-v1\evaluation.json`

最终结果：

| 指标 | 结果 |
| --- | ---: |
| 任务数 | 50 |
| PASS | 47 |
| 通过率 / 旧 PASS 保留率 | 94.0% |
| 未通过 task id | 5、87、243 |
| 完成时间 | 2026-09-17 19:20:47 +08:00 |
| 模型 | qwen3.8-27b |

评测文件的注释为“Host-only canary evaluation; gold was unavailable during inference”，含义是 gold 未在推理期间暴露，评测在宿主机进行；它不是公开 leaderboard 提交。

### 8.5 全量外推（必须带限制）

保守计算：

`(267 × 0.94 + 153 × 0.44) / 500 = 63.7%`

即 New SignalPilot 全量 BIRD-mini-dev 暂估 **约 64%**，以两个 50 题样本的抽样波动估计实用区间约 **58%–69%**。

若余下 80 个旧 SQL 错误任务也达到 44% 的恢复率，乐观上限约 71%，但没有样本支持，**不得写成正式结果**。94% 仅表示对旧 PASS 群体的保留率，不能写为完整 500 题准确率。

本轮工作报告和 PPT 提纲：

- `P11\New_SignalPilot_轻量Mapper改进与实验工作报告_20260917.md`
- `P11\New_SignalPilot_轻量Mapper实验_PPT生成提纲_20260917.md`

---

## 9. 代码与验收状态

最近一次 BIRD 离线验证记录为：

- `test_offline_workflow.py` 与 `test_qwen_runner_isolation.py` 合计 **22/22 通过**；
- Python 与 PowerShell 语法检查通过；
- BIRD runner 固定本地 Qwen route，不使用 DeepSeek 凭据；
- BIRD/Spider runtime namespace 分离测试通过。

新接手者在任何生产运行前应重新执行现有 `scripts\preflight.ps1 -RequireData`；如果代码被修改，旧 RunId 的 source hash 校验会拒绝 resume，这是预期保护。

---

## 10. 未完成事项与建议顺序

### P0：先做只读复核

1. 读取 BIRD 当前 `agent_entry.py`、`meta_controller.py`、`run_canary_three.ps1`，确认确定性 Mapper、候选写入、Verifier 证据协议仍与本交接一致；
2. 检查 Docker Desktop、SSH 隧道和 Qwen route；
3. 读取旧 Run manifest 与 terminal artifact，确认没有遗留运行容器；
4. 重新运行 BIRD API-free preflight，不要直接修改代码。

### P1：验证全量外推

优先对旧版 80 个“已有 SQL 但官方错误”任务进行分层抽样或全量复测。该群体决定 64% 外推是否保守、准确或过高。不要把 50 题旧 PASS 的 94% 直接宣传为全量成绩。

### P2：针对官方口径歧义改进

按失败类型设计有限、可审计的候选分支：

- COUNT 与 DISTINCT；
- ID 与名称投影；
- JOIN 粒度与 fanout；
- 排序、Top-K 与输出列。

禁止用 hidden gold 或评测文件硬编码任务答案。候选比较必须保持在公开题目、schema 和数据库数据范围内。

### P3：修复宿主 runner 收尾

实现一个独立宿主 Supervisor，至少保证：

- 容器结束后原子复制产物并写 `terminal.json`；
- `run_manifest` 的状态只能在提交成功后更新；
- 出现 launcher 退出时，下一次 resume 能识别“任务已完成但未提交”的状态并进行安全收口；
- 记录 launcher PID、Docker 容器 id、最后心跳和失败原因；
- 不依赖当前 Codex 窗口、短生命周期 PowerShell 或失败的 Task Scheduler；
- 对中断、隧道断开、Docker 退出和容器非零退出做故障注入。

### P4：Spider M2 与全量

在 Spider 上完成 M2 的真实 runner 迁移前，不要把 M1 离线原语称为完整四容器架构。应先补齐真实 Docker 阶段编排、mount inspect/mountinfo 证据、resume 状态机与故障注入，再在 Preparation 合同复审后启动全量。

---

## 11. 不要重复犯的错误

- 不要以 manifest 的 `RUNNING` 唯一判断实验仍在运行；必须结合最新产物时间、`terminal.json`、宿主进程和 Docker 容器。
- 不要在 SSH 隧道关闭时继续跑实验；`18020` 连接拒绝时，兼容路由会返回 502，runner 将浪费重试并可能留下半完成任务。
- 不要误把 `15721/v1/models` 返回空 models 当作故障；该兼容层可正常转发 `/v1/messages`。
- 不要重启或停止共享 node3 vLLM 服务。
- 不要混用 Spider 与 BIRD 的工作目录、容器或结果目录。
- 不要因追求“删除缓存 relation 数量”而删除有公开 source 证据的输入 relation。
- 不要让 Verifier 的 PASS/FAIL 覆盖官方评测结果。
- 不要对已写 `terminal.json` 的任务重新运行；resume 应跳过它们。
- 任何代码/镜像/参数变更后，使用新 RunId，不要强行 resume 旧 Hash。
