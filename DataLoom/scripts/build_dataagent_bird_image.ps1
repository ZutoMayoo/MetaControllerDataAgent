param(
    [string]$DataAgentRoot = "",
    [string]$Image = "dataloom-dataagent-bird:8208e7c"
)

$ErrorActionPreference = "Stop"
$workspace = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
if (-not $DataAgentRoot) {
    $DataAgentRoot = Join-Path $workspace "external\DataAgent"
}
$dataAgentRootResolved = (Resolve-Path -LiteralPath $DataAgentRoot).Path
$runtimeAssets = Join-Path $workspace "runtime-assets\DataAgent"
New-Item -ItemType Directory -Force -Path $runtimeAssets | Out-Null
$runtimeAssetsResolved = (Resolve-Path -LiteralPath $runtimeAssets).Path
$staging = Join-Path $runtimeAssetsResolved ("docker-build-" + [guid]::NewGuid().ToString("N"))
$archive = Join-Path $staging "dataagent-source.tar"
$runner = Join-Path $workspace "P12\DataLoom\runtime\bird_gold_safe.py"
$dockerfile = Join-Path $workspace "P12\DataLoom\docker\DataAgentBird.Dockerfile"

try {
    New-Item -ItemType Directory -Path $staging | Out-Null
    & git -c "safe.directory=$($dataAgentRootResolved.Replace('\','/'))" -C $dataAgentRootResolved `
        archive --format=tar --output $archive HEAD runtime/dataagent
    if ($LASTEXITCODE -ne 0) {
        throw "git archive failed"
    }
    & tar -xf $archive -C $staging
    if ($LASTEXITCODE -ne 0) {
        throw "source archive extraction failed"
    }
    Copy-Item -LiteralPath $runner -Destination (Join-Path $staging "bird_gold_safe.py")
    & docker build -f $dockerfile -t $Image $staging
    if ($LASTEXITCODE -ne 0) {
        throw "Docker image build failed"
    }
    & docker image inspect $Image --format '{{.Id}}|{{.Size}}'
    if ($LASTEXITCODE -ne 0) {
        throw "Docker image verification failed"
    }
}
finally {
    if (Test-Path -LiteralPath $staging) {
        $stagingResolved = (Resolve-Path -LiteralPath $staging).Path
        $expectedPrefix = $runtimeAssetsResolved.TrimEnd('\') + '\docker-build-'
        if (-not $stagingResolved.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "refusing to clean unexpected staging path: $stagingResolved"
        }
        Remove-Item -LiteralPath $stagingResolved -Recurse -Force
    }
}
