$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$CacheRoot = Join-Path $ProjectRoot '.cache'

$env:UV_CACHE_DIR = Join-Path $CacheRoot 'uv'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $CacheRoot 'uv-python'
$env:UV_PROJECT_ENVIRONMENT = Join-Path $ProjectRoot '.venv'
$env:HF_HOME = Join-Path $CacheRoot 'huggingface'
$env:HUGGINGFACE_HUB_CACHE = Join-Path $env:HF_HOME 'hub'
$env:TORCH_HOME = Join-Path $CacheRoot 'torch'
$env:XDG_CACHE_HOME = $CacheRoot
$env:PIP_CACHE_DIR = Join-Path $CacheRoot 'pip'
$env:TEMP = Join-Path $CacheRoot 'tmp'
$env:TMP = $env:TEMP
$env:HF_HUB_DISABLE_TELEMETRY = '1'

@(
    $env:UV_CACHE_DIR,
    $env:UV_PYTHON_INSTALL_DIR,
    $env:HF_HOME,
    $env:HUGGINGFACE_HUB_CACHE,
    $env:TORCH_HOME,
    $env:PIP_CACHE_DIR,
    $env:TEMP
) | ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }
