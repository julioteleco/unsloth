# Bootstrap local install for market-flow-risk-heatmap (Windows PowerShell).
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectDir

$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }

Write-Host "==> Using Python: $(& $PythonBin -V)"
& $PythonBin -c "import sys; assert sys.version_info >= (3, 11)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required. Set PYTHON_BIN to a 3.11+ interpreter." }

Write-Host "==> Creating virtualenv (.venv)"
& $PythonBin -m venv .venv

$Activate = Join-Path $ProjectDir ".venv\Scripts\Activate.ps1"
. $Activate

Write-Host "==> Upgrading pip"
pip install --upgrade pip | Out-Null

Write-Host "==> Installing requirements"
pip install -r requirements.txt

if ((-not (Test-Path ".env")) -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> Created .env from .env.example (FRED_API_KEY is optional)"
}

Write-Host "==> Running test suite"
python -m pytest -q

Write-Host @"

============================================================
 Instalacion completada.

 Para usar el proyecto (con el venv activado):
   .venv\Scripts\Activate.ps1

 1) Descargar datos reales (necesita internet -> Yahoo Finance):
      python scripts\download_data.py --period 60d --interval 5m

 2) Construir features + diagnostico de un ticker:
      python scripts\build_features.py --ticker SPY

 3) Lanzar el dashboard (abre http://localhost:8501):
      streamlit run app\streamlit_app.py
============================================================
"@
