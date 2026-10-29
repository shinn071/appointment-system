$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$venvConfig = Join-Path $PSScriptRoot ".venv\pyvenv.cfg"
if (-not ((Test-Path -LiteralPath $pythonExe) -and (Test-Path -LiteralPath $venvConfig))) {
    throw "The Python environment is missing or incomplete. Run .\run-local.ps1 once first."
}

& $pythonExe (Join-Path $PSScriptRoot "setup-local-https.py")
if ($LASTEXITCODE -ne 0) {
    throw "Could not create the local HTTPS certificate."
}

$certificatePath = Join-Path $PSScriptRoot "instance\campus-clinic-local-ca.cer"
$certutil = Join-Path $env:WINDIR "System32\certutil.exe"
& $certutil -user -addstore Root $certificatePath
if ($LASTEXITCODE -ne 0) {
    throw "Windows could not add the local certificate authority to your current-user trust store."
}

Write-Host "Trusted the Campus Clinic development certificate for this Windows user."
Write-Host "Open https://localhost:3000/ in your browser."
