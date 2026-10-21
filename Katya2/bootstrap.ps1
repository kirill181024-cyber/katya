#requires -version 5
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$AppDir = $PSScriptRoot
Set-Location $AppDir

function Info($m)  { Write-Host "  $m" -ForegroundColor Cyan }
function Ok($m)    { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m)  { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Fail($m)  { Write-Host "  [X] $m" -ForegroundColor Red }

function Download($url, $dest) {
    Info "Downloading $(Split-Path $url -Leaf) ..."
    $wc = New-Object System.Net.WebClient
    $wc.DownloadFile($url, $dest)
}

function Find-Python {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python"),
        "C:\Python311", "C:\Python312", "C:\Python313", "C:\Python314"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) {
            $exe = Get-ChildItem $c -Recurse -Filter "python.exe" -ErrorAction SilentlyContinue |
                   Where-Object { $_.FullName -notmatch "WindowsApps" } | Select-Object -First 1
            if ($exe) { return $exe.FullName }
        }
    }
    foreach ($name in @("python", "python3", "py")) {
        $g = Get-Command $name -ErrorAction SilentlyContinue
        if ($g -and $g.Source -notmatch "WindowsApps") { return $g.Source }
    }
    return $null
}

function Install-Python {
    $ver = "3.12.7"
    $exe = Join-Path $env:TEMP "python-$ver-amd64.exe"
    $url = "https://www.python.org/ftp/python/$ver/python-$ver-amd64.exe"
    Download $url $exe
    Info "Installing Python $ver (silent) ..."
    $args = "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=1 SimpleInstall=1"
    Start-Process -FilePath $exe -ArgumentList $args -Wait
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    # refresh PATH for this process
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path","User")
}

function Find-Ollama {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"),
        "C:\Program Files\Ollama\ollama.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $g = Get-Command ollama -ErrorAction SilentlyContinue
    if ($g) { return $g.Source }
    return $null
}

function Install-Ollama {
    $exe = Join-Path $env:TEMP "OllamaSetup.exe"
    Download "https://ollama.com/download/OllamaSetup.exe" $exe
    Info "Installing Ollama (silent) ..."
    Start-Process -FilePath $exe -ArgumentList "/VERYSILENT" -Wait
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
}

function Ensure-OllamaRunning($ollamaExe) {
    try {
        Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
        return $true
    } catch {}
    Info "Starting Ollama service ..."
    Start-Process -FilePath $ollamaExe -ArgumentList "serve" -WindowStyle Hidden
    for ($i=0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        try {
            Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3 | Out-Null
            return $true
        } catch {}
    }
    return $false
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "   KATYA 2.10 - FULL SETUP (press-and-go)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

# 1) Python
$python = Find-Python
if (-not $python) {
    Warn "Python not found. Installing it automatically ..."
    Install-Python
    $python = Find-Python
}
if (-not $python) { Fail "Python could not be installed. Install manually from python.org"; Read-Host "Press Enter"; exit 1 }
Ok "Python: $python"

# 2) venv + dependencies
if (-not (Test-Path ".venv\Scripts\pythonw.exe")) {
    Info "Creating virtual environment ..."
    & $python -m venv .venv
}
Info "Installing Python packages ..."
& ".venv\Scripts\python.exe" -m pip install --upgrade pip --disable-pip-version-check | Out-Null
& ".venv\Scripts\python.exe" -m pip install -r requirements.txt --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { Fail "pip install failed. Check internet."; Read-Host "Press Enter"; exit 1 }
Ok "Dependencies installed"

# 3) Ollama
$ollamaExe = Find-Ollama
if (-not $ollamaExe) {
    Warn "Ollama not found. Installing it automatically ..."
    Install-Ollama
    $ollamaExe = Find-Ollama
}
if (-not $ollamaExe) { Fail "Ollama could not be installed."; Read-Host "Press Enter"; exit 1 }
Ok "Ollama: $ollamaExe"

# 4) model
if (Ensure-OllamaRunning $ollamaExe) {
    $list = & $ollamaExe list 2>&1 | Out-String
    if ($list -notmatch "gemma3") {
        Write-Host ""
        Info "Downloading AI model gemma3:4b (~3.4 GB, runs on GPU). This can take a while ..."
        & $ollamaExe pull gemma3:4b
    } else {
        Ok "Model gemma3:4b already present"
    }
} else {
    Warn "Ollama service is not responding; the model will download on first run."
}

Ok "Everything is ready. Launching Katya ..."
Start-Process -FilePath ".venv\Scripts\pythonw.exe" -ArgumentList "main.py" -WorkingDirectory $AppDir -WindowStyle Hidden
exit 0
