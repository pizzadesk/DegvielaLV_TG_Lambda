param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")),
    [string]$OutputZip = "lambda-deployment.zip",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

$buildDir = Join-Path $ProjectRoot ".build_lambda"
$zipPath = Join-Path $ProjectRoot $OutputZip

if (Test-Path $buildDir) {
    Remove-Item $buildDir -Recurse -Force
}
New-Item -ItemType Directory -Path $buildDir | Out-Null

& $PythonExe -m pip install --upgrade pip | Out-Null
& $PythonExe -m pip install -r (Join-Path $ProjectRoot "requirements.txt") -t $buildDir

Copy-Item (Join-Path $ProjectRoot "lambda_function.py") $buildDir
Copy-Item (Join-Path $ProjectRoot "fuel_price_telegram_bot") $buildDir -Recurse

if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

Compress-Archive -Path (Join-Path $buildDir "*") -DestinationPath $zipPath -Force

Write-Host "Created $zipPath"
