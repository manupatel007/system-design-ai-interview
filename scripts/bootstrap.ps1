param(
    [switch]$SkipModels
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'env.ps1')

uv sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipModels) {
    uv run python scripts/download_models.py --all
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

uv run voice-interviewer doctor
