param(
    [Parameter(Mandatory = $true)][string]$BundleDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$Image = "dataloom-dataagent-bird:8208e7c",
    [string]$SemanticServiceUrl = "http://host.docker.internal:32000",
    [string]$ApiBase = "http://host.docker.internal:18020/v1",
    [string]$Model = "qwen3.8-27b",
    [string]$SemanticDbPrefix = "bird_dataloom"
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
$runner = Join-Path $workspace "P12\DataLoom\runtime\bird_gold_safe.py"
$bundleResolved = (Resolve-Path -LiteralPath $BundleDir).Path
& python $runner audit --bundle-dir $bundleResolved | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Gold-free bundle audit failed"
}

if (Test-Path -LiteralPath $OutputDir) {
    $outputResolved = (Resolve-Path -LiteralPath $OutputDir).Path
    if (Get-ChildItem -LiteralPath $outputResolved -Force) {
        throw "OutputDir must be empty: $outputResolved"
    }
}
else {
    New-Item -ItemType Directory -Path $OutputDir | Out-Null
    $outputResolved = (Resolve-Path -LiteralPath $OutputDir).Path
}

$containerName = "dataloom-bird-infer-" + [guid]::NewGuid().ToString("N").Substring(0, 12)
& docker run --rm --name $containerName `
    --read-only --cap-drop ALL --security-opt no-new-privileges `
    --pids-limit 256 --memory 8g `
    --mount "type=bind,source=$bundleResolved,target=/input,readonly" `
    --mount "type=bind,source=$outputResolved,target=/output" `
    --tmpfs "/tmp:rw,noexec,nosuid,size=512m" `
    -e DATAAGENT_HOME=/output/dataagent_home `
    -e LLM_API_KEY=local-qwen `
    $Image `
    --bundle-dir /input `
    --output-dir /output/inference `
    --semantic-service-url $SemanticServiceUrl `
    --semantic-db-prefix $SemanticDbPrefix `
    --model $Model `
    --api-base $ApiBase
if ($LASTEXITCODE -ne 0) {
    throw "isolated DataAgent inference failed"
}

$candidate = Join-Path $outputResolved "inference\candidate.json"
$digest = Join-Path $outputResolved "inference\candidate.sha256"
if (-not (Test-Path -LiteralPath $candidate -PathType Leaf) -or
    -not (Test-Path -LiteralPath $digest -PathType Leaf)) {
    throw "container exited without a frozen candidate"
}
Get-FileHash -LiteralPath $candidate -Algorithm SHA256
