param(
    [string]$DataAgentRoot = "",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
if (-not $DataAgentRoot) {
    $DataAgentRoot = Join-Path $workspace "external\DataAgent"
}
$packageRoot = Join-Path $DataAgentRoot "runtime\dataagent"
$pyproject = Join-Path $packageRoot "pyproject.toml"
if (-not (Test-Path -LiteralPath $pyproject -PathType Leaf)) {
    throw "External DataAgent pyproject.toml not found: $pyproject"
}
$environment = Join-Path $packageRoot ".venv-dataloom-bird"
$environmentPython = Join-Path $environment "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $environmentPython -PathType Leaf)) {
    & $Python -m venv $environment
}
& $environmentPython -m pip install -e "$packageRoot[nl2sql]"
& $environmentPython -m pip check
& $environmentPython -m dataagent.core.suite.builtin_suites.bird_benchmark.run_bird --help
