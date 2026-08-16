$ErrorActionPreference = 'Stop'
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$FrontendRoot = Join-Path $ProjectRoot 'frontend'
$StoreRoot = Join-Path $ProjectRoot '.cache\pnpm-store'
$env:npm_config_cache = Join-Path $ProjectRoot '.cache\npm'

pnpm --dir $FrontendRoot --store-dir $StoreRoot install --frozen-lockfile
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

pnpm --dir $FrontendRoot test
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

pnpm --dir $FrontendRoot build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
