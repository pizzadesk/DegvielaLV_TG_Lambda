param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [string]$OutputZip = "lambda-deployment.zip",
    [string]$PythonExe = "python",
    [switch]$IncludeBoto3,
    [switch]$UpgradePip
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)]
        [string]$File,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed ($LASTEXITCODE): $File $($Arguments -join ' ')"
    }
}

$buildDir = Join-Path $ProjectRoot ".build_lambda"
$zipPath = Join-Path $ProjectRoot $OutputZip

if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
    throw "Python executable not found: $PythonExe"
}

if (Test-Path $buildDir) {
    Remove-Item $buildDir -Recurse -Force
}
New-Item -ItemType Directory -Path $buildDir | Out-Null

$previousPipUser = $env:PIP_USER
$env:PIP_USER = '0'

try {
    if ($UpgradePip) {
        Invoke-External $PythonExe -m pip install --upgrade pip
    }

    Invoke-External $PythonExe -m pip install --disable-pip-version-check --no-compile -r (Join-Path $ProjectRoot "requirements.txt") -t $buildDir
}
finally {
    if ($null -eq $previousPipUser) {
        Remove-Item Env:PIP_USER -ErrorAction SilentlyContinue
    }
    else {
        $env:PIP_USER = $previousPipUser
    }
}

if (-not $IncludeBoto3) {
    foreach ($name in @('boto3', 'botocore', 's3transfer', 'jmespath')) {
        Get-ChildItem -Path $buildDir -Filter "$name*" -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Get-ChildItem -Path $buildDir -Directory -Filter "__pycache__" -Recurse -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -Path $buildDir -File -Include "*.pyc", "*.pyo" -Recurse -Force | Remove-Item -Force -ErrorAction SilentlyContinue

foreach ($requiredPath in @('telegram', 'requests', 'bs4')) {
    if (-not (Test-Path (Join-Path $buildDir $requiredPath))) {
        throw "Dependency install incomplete. Missing in build directory: $requiredPath"
    }
}

Copy-Item (Join-Path $ProjectRoot "lambda_function.py") $buildDir
Copy-Item (Join-Path $ProjectRoot "fuel_price_telegram_bot") $buildDir -Recurse

if (-not (Test-Path (Join-Path $buildDir "fuel_price_telegram_bot\bot.py"))) {
    throw "Project copy failed: fuel_price_telegram_bot/bot.py not found in build directory"
}

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive -Path (Join-Path $buildDir "*") -DestinationPath $zipPath -Force

if (-not (Test-Path $zipPath)) {
    throw "Zip creation failed: $zipPath"
}

Write-Host "Created $zipPath"
