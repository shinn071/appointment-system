param(
    [switch]$Http
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$pythonExe = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$venvConfig = Join-Path $PSScriptRoot ".venv\pyvenv.cfg"
if (-not ((Test-Path -LiteralPath $pythonExe) -and (Test-Path -LiteralPath $venvConfig))) {
    $pyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        & $pyLauncher.Source -3 -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Python could not create the virtual environment. Install Python 3 from python.org and retry."
        }
    } else {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if (-not $pythonCommand) {
            throw "Python 3 is not installed or not on PATH, or the existing .venv is incomplete. Install Python 3, reopen PowerShell, and run .\run-local.ps1 again."
        }
        & $pythonCommand.Source -m venv .venv
        if ($LASTEXITCODE -ne 0) {
            throw "Python could not create the virtual environment. Install Python 3 from python.org and retry."
        }
    }
}

Write-Host "Installing or checking Campus Clinic dependencies..."
& $pythonExe -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    throw "Dependency installation failed. Check your internet connection and Python installation, then retry."
}

if (-not $env:CAMPUS_CLINIC_SECRET_KEY) {
    $secretPath = Join-Path $PSScriptRoot "instance\flask-secret-key"
    if (-not (Test-Path -LiteralPath $secretPath)) {
        $secret = (& $pythonExe -c "import secrets; print(secrets.token_hex(32))").Trim()
        Set-Content -LiteralPath $secretPath -Value $secret -NoNewline
    }
    $env:CAMPUS_CLINIC_SECRET_KEY = (Get-Content -LiteralPath $secretPath -Raw).Trim()
}

if ($Http) {
    $env:CAMPUS_CLINIC_COOKIE_SECURE = "0"
    Write-Host "Starting local HTTP server at http://localhost:3000/"
    Write-Host "Warning: cookies are not Secure in HTTP mode. Use HTTPS for normal development."
    & $pythonExe -m flask --app app run --host localhost --port 3000
} else {
    $certificatePath = Join-Path $PSScriptRoot "instance\localhost-cert.pem"
    $privateKeyPath = Join-Path $PSScriptRoot "instance\localhost-key.pem"
    $trustedCaPath = Join-Path $PSScriptRoot "instance\campus-clinic-local-ca.cer"
    if (-not ((Test-Path -LiteralPath $certificatePath) -and (Test-Path -LiteralPath $privateKeyPath) -and (Test-Path -LiteralPath $trustedCaPath))) {
        Write-Host "Setting up a trusted localhost HTTPS certificate..."
        & (Join-Path $PSHOME "powershell.exe") -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "setup-https.ps1")
        if ($LASTEXITCODE -ne 0) {
            throw "HTTPS setup failed. Run powershell -ExecutionPolicy Bypass -File .\setup-https.ps1 and review its error."
        }
    }
    $env:CAMPUS_CLINIC_COOKIE_SECURE = "1"
    Write-Host "Starting local HTTPS server at https://localhost:3000/"
    & $pythonExe -m flask --app app run --host localhost --port 3000 --cert $certificatePath --key $privateKeyPath
}

if ($LASTEXITCODE -ne 0) {
    throw "Campus Clinic stopped with an error. Read the Flask message above. If port 3000 is already in use, close the other app using it or choose another port."
}
