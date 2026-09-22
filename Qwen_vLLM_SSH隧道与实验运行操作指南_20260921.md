# Qwen vLLM SSH 隧道与实验运行操作指南

日期：2026-09-21  
适用项目：`D:\GraduationProject\ProgressReport\P9\optimizedAgent\clean_replay`（Spider）与 `D:\GraduationProject\ProgressReport\P10\BIRD-MetaController`（BIRD）

## 1. 本次检查结论

检查时本机已有 `ssh.exe` 进程（PID 会随重连而变化）并监听 `127.0.0.1:18020`，但：

- 请求 `http://127.0.0.1:18020/v1/models` 被连接重置；
- 请求本机兼容路由 `http://127.0.0.1:15721/v1/messages` 返回 `502 Bad Gateway`；
- `http://127.0.0.1:15721/v1/models` 返回 `{"models":[]}`。

随后在 node3 的直接检查确认：旧远端 8888 已停止监听；当前 8899 与 8889 都可返回 `qwen3.8-27b`。本指南固定 **8899 为主端口**，8889 只作明确验证后的备用端口。原 SSH 隧道指向 8888，因此实际转发通道已不可用。**此状态不能启动实验。** 必须先按下列步骤替换隧道并验证模型响应。

注意：兼容层 `/v1/models` 的空列表是正常现象，不能用它判定 Qwen 服务是否可用；必须以 `18020/v1/models` 和 `15721/v1/messages` 两个检查为准。

---

## 2. 固定网络拓扑

```text
Docker 容器
  └─ http://host.docker.internal:15721/v1/messages
       └─ 本机 Anthropic 兼容路由 127.0.0.1:15721
            └─ SSH 本地转发 127.0.0.1:18020
                 └─ node3 的 127.0.0.1:8899
                      └─ vLLM: qwen3.8-27b
```

当前主远端模型端口是 **8899**，备用端口是 **8889**；旧的 8888 和 8020 都不可用。不要让一个隧道在两端口之间随意切换，以免实验期间路由漂移。

远端登录信息：

```text
host: 115.236.33.122
ssh port: 8803
user: chengyichao
primary remote model port: 127.0.0.1:8899
fallback remote model port: 127.0.0.1:8889
model id: qwen3.8-27b
```

远端 vLLM 是共享服务。除非获得服务所有者确认，**不要 stop、kill 或 restart vLLM**。

---

## 3. 标准恢复流程

所有命令均在 Windows PowerShell 中运行。

### 3.1 先识别占用 18020 的进程

```powershell
netstat -ano | Select-String ':18020'
Get-Process -Id <上一步显示的PID>
```

预期是一个 `ssh` 进程。若 PID 不属于 SSH，不要结束它，先确认该端口是否由其他用户服务占用。

### 3.2 仅结束确认无效的旧 SSH 隧道

在已确认 PID 是旧隧道进程后：

```powershell
Stop-Process -Id <旧SSH的PID>
```

然后确认端口已释放：

```powershell
netstat -ano | Select-String ':18020'
```

无输出才表示端口已释放。不要使用“结束所有 ssh 进程”的宽泛命令，以免杀掉其他会话。

### 3.3 在独立 PowerShell 窗口建立新隧道

打开一个**专用、不要关闭**的 PowerShell 窗口，运行：

```powershell
ssh -N -T `
  -o ExitOnForwardFailure=yes `
  -o ConnectTimeout=15 `
  -o ServerAliveInterval=30 `
  -o ServerAliveCountMax=3 `
  -o TCPKeepAlive=yes `
  -L 127.0.0.1:18020:127.0.0.1:8899 `
  -p 8803 chengyichao@115.236.33.122
```

输入密码后，窗口通常不再输出内容且保持占用，这正是正常状态。不要在该窗口按 `Ctrl+C`，不要关闭窗口，也不要让电脑睡眠或关机。

`ExitOnForwardFailure=yes` 很重要：若本地 18020 无法绑定，命令会立即退出，而不是留下看似可用的假隧道。

---

## 4. 逐层验收：必须全部通过

请在**另一个** PowerShell 窗口执行下列检查。

### 4.1 检查本地 SSH 转发是否直接看到远端模型

```powershell
curl.exe -sS --max-time 10 http://127.0.0.1:18020/v1/models
```

通过标准：JSON 的 `data` 中含有：

```json
{"id":"qwen3.8-27b"}
```

失败解释：

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `Failed to connect` / 连接拒绝 | 没有本地监听器 | 重建 SSH 隧道 |
| `Recv failure: Connection was reset` | 本地 ssh 存活但远端转发已坏 | 按 3.1–3.3 完整替换隧道；若仍发生，做 4.4 远端检查 |
| `channel open failed: connect failed: Connection refused` | SSH 可连但当前选定的远端端口没有服务 | 先验证 8899；必要时明确改用备用 8889；不要擅自重启 vLLM |
| 返回的 model id 不同 | 连接到错误服务或服务器配置改变 | 停止实验，核对远端服务 |

### 4.2 检查本地兼容路由

`/v1/models` 的空列表正常：

```powershell
curl.exe -sS --max-time 10 http://127.0.0.1:15721/v1/models
```

这可能返回：

```json
{"models":[]}
```

真正的端到端检查是发送一个很短的消息：

```powershell
$headers = @{
  'x-api-key' = 'local-vllm-placeholder'
  'anthropic-version' = '2023-06-01'
  'content-type' = 'application/json'
}

$body = @{
  model = 'qwen3.8-27b'
  max_tokens = 8
  messages = @(@{ role = 'user'; content = 'Reply exactly: ROUTE_OK' })
} | ConvertTo-Json -Depth 8

Invoke-RestMethod `
  -Uri 'http://127.0.0.1:15721/v1/messages' `
  -Method Post `
  -Headers $headers `
  -Body $body
```

通过标准：返回对象中 `content.text` 为 `ROUTE_OK` 或等价简短响应，且 HTTP 状态为 200。

若返回 502，不要运行实验：先重做 4.1；若 4.1 已通过，检查本机兼容路由的上游配置和日志。

### 4.3 检查 Docker 能访问兼容路由

容器使用的 endpoint 是 `http://host.docker.internal:15721`，而非 `127.0.0.1:15721`。先运行项目预检：

```powershell
& .\P10\BIRD-MetaController\scripts\preflight.ps1 -RequireData
```

预检只检查本地数据、镜像和离线测试；它不能取代 4.2 的实际模型请求。实际 BIRD run 的容器日志中若出现 Qwen 的正常 Turn 记录，表示 Docker→兼容层→SSH→vLLM 链路已通。

### 4.4 可选：在远端直接确认 vLLM

仅在 4.1 失败而 SSH 可登录时，新开一个普通 SSH 会话：

```powershell
ssh -p 8803 chengyichao@115.236.33.122
```

进入远端后执行只读检查：

```bash
hostname
ss -ltn | grep -E ':8899|:8889'
curl -sS --max-time 5 http://127.0.0.1:8899/v1/models
curl -sS --max-time 5 http://127.0.0.1:8889/v1/models
ps -ef | grep -E '[v]llm|[q]wen3.8-27b'
```

预期：8899（主端口）为 `LISTEN`，models 响应含 `qwen3.8-27b`；8889 可作为备用。若两者都未监听或 curl 失败，把输出交给服务器管理员；本项目侧不要修改远端 vLLM。

---

## 5. 启动实验前的共同检查清单

在启动 Spider 或 BIRD 前确认：

1. 4.1 和 4.2 都通过；
2. SSH 隧道窗口仍保持打开；
3. Docker Desktop 正在运行；
4. 电脑不会自动睡眠；
5. 没有同项目的遗留运行容器；
6. 运行目录、模型和代码 Hash 与准备 resume 的 manifest 一致；
7. `PAID_API_DISABLED` 标记存在。它防止意外使用付费供应商，不会阻断明确配置的本地 Qwen。

检查 BIRD 已有容器时，按 run label 过滤：

```powershell
docker ps -a --filter 'label=bird.run=<runid小写>'
```

检查 Spider 时必须使用 Spider 自己的标签/命名规则，不要误杀 BIRD 容器。

---

## 6. BIRD 操作命令

项目根：

```powershell
Set-Location D:\GraduationProject\ProgressReport
```

### 6.1 新运行（示例）

```powershell
& .\P10\BIRD-MetaController\scripts\run_canary_three.ps1 `
  -ConfirmRun `
  -RunId bird-qwen-<日期或实验名> `
  -Tasks '305,472,46' `
  -Model qwen3.8-27b
```

### 6.2 恢复同一 RunId

仅在代码、镜像、模型、任务集和预算参数都没有改变时：

```powershell
& .\P10\BIRD-MetaController\scripts\run_canary_three.ps1 `
  -ConfirmRun -Resume `
  -RunId <旧RunId> `
  -Tasks '<必须与run_manifest.json完全相同的列表>' `
  -Model qwen3.8-27b `
  -MainTurns 70 -RoleTurns 35 -RepairTurns 40 `
  -VerifierQueryBudget 12 -VerifierFinalizerTurns 3
```

若源代码 Hash 不同，resume 会拒绝，这是预期安全保护；改代码后请使用新 RunId。

任务是否完成以 `results\<RunId>\bird-<id>\terminal.json` 为准。只有 `candidate.sql` 但没有 `terminal.json` 的任务会在 resume 时被安全重跑，因为数据库 snapshot 是独立只读挂载。

---

## 7. Spider 操作说明

Spider 运行入口：

```powershell
& .\P9\optimizedAgent\clean_replay\run_full_experiment.ps1 `
  -Provider QwenCCSwitch `
  -Model qwen3.8-27b `
  -RunId <新RunId> `
  -PreflightOnly
```

先使用 `-PreflightOnly` 验证 API-free controller tests 和 Container import smoke。正式运行时须阅读该脚本当前参数并显式确认全量运行选项。

Spider 曾多次在宿主 runner 收尾时留下假性 `RUNNING` manifest。恢复前必须同时检查：最新任务产物时间、hash-matched terminal artifact、关联 Docker 容器和宿主 launcher，而不是只看 manifest。

---

## 8. 运行中异常的处理

### 8.1 容器日志连续出现 `api_retry` / 502

立即暂停新任务调度，不要让所有任务耗尽重试。按以下顺序检查：

1. 4.1：18020 是否返回 `qwen3.8-27b`；
2. 4.2：15721 `/v1/messages` 是否 200；
3. SSH 隧道窗口是否关闭、断开或进入异常状态；
4. 远端主端口 8899 是否仍监听；必要时核对备用端口 8889。

恢复通道后，如代码未变，可对同一 RunId resume；不要因为 502 修改 Agent 或换用隐藏 gold。

### 8.2 `Refusing to start while ... container(s) are already running`

先列出容器并按 label 确认归属。BIRD 和 Spider 可以同时存在，但同一 runner 不应与同一 RunId 的容器重叠。不要用不加过滤的 Docker 清理命令。

### 8.3 manifest 为 `RUNNING`，但实验无新产物

检查：

```powershell
Get-ChildItem <Run目录> -Recurse -File |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 10 FullName,LastWriteTime
```

若没有近期产物、没有关联容器或 launcher 进程，则 runner 实际已停止。对已完成任务以 `terminal.json` 为准，使用同一 RunId resume；若中断点处只有 work 产物没有 `terminal.json`，该任务会被安全重放。

---

## 9. 最终原则

- 本机端口 18020 是 SSH 隧道，不是 vLLM 本身；进程存在不等于隧道可用。当前主隧道必须指向远端 8899。
- 15721 的空 models 列表正常，`/v1/messages` 成功才算路由正常。
- Qwen、Docker 和 SSH 链路通过前，禁止启动正式实验。
- 保持 BIRD 与 Spider 的目录、容器标签、结果目录和 SDK 路径隔离。
- 不要重启共享远端 vLLM；遇到远端 8899 与 8889 都不监听时联系服务器管理员。
