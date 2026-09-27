param(
    [switch]$CheckOnly,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"

try {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $AppDir = Split-Path -Parent $ScriptDir

    $HomeDir = $env:MENUSTUDIO_HOME
    if (-not $HomeDir) {
        $HomeDir = Join-Path $env:LOCALAPPDATA "MenuStudio"
    }
    New-Item -ItemType Directory -Force -Path $HomeDir | Out-Null

    $env:MENUSTUDIO_HOME = $HomeDir
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $HomeDir "python"
    $env:UV_CACHE_DIR = Join-Path $HomeDir "uv-cache"
    $env:UV_LINK_MODE = "copy"
    $env:PYTHONUTF8 = "1"

    Write-Host "Menu Studio -- first start takes 3-8 minutes (downloads ~700 MB once). Later starts take seconds." -ForegroundColor Cyan

    # [1/4] Already running?
    Write-Host "[1/4] Checking for a running instance..." -ForegroundColor Cyan
    $ServerFile = Join-Path $HomeDir "server.json"
    if (Test-Path $ServerFile) {
        try {
            $info = Get-Content $ServerFile -Raw | ConvertFrom-Json
            $existingPort = [int]$info.port
        } catch {
            $existingPort = 0
        }
        if ($existingPort) {
            $healthOk = $false
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$existingPort/api/health" -UseBasicParsing -TimeoutSec 2
                if ($resp.Content -like "*menustudio*") {
                    $healthOk = $true
                }
            } catch {
                $healthOk = $false
            }
            if ($healthOk) {
                if (-not $CheckOnly) {
                    Start-Process "http://127.0.0.1:$existingPort/"
                }
                Write-Host "Menu Studio is already open in your browser." -ForegroundColor Green
                exit 0
            }
        }
    }

    # [2/4] Python
    Write-Host "[2/4] Setting up Python..." -ForegroundColor Cyan
    $Py = Join-Path $HomeDir "venv\Scripts\python.exe"
    $Uv = Join-Path $HomeDir "tools\uv.exe"

    if (-not (Test-Path $Py)) {
        $uvReady = Test-Path $Uv
        if (-not $uvReady) {
            try {
                $toolsDir = Join-Path $HomeDir "tools"
                New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
                $uvZip = Join-Path $toolsDir "uv.zip"
                $uvUrl = "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip"
                $downloaded = $false
                for ($attempt = 1; $attempt -le 2; $attempt++) {
                    try {
                        Invoke-WebRequest -Uri $uvUrl -OutFile $uvZip -UseBasicParsing
                        $downloaded = $true
                        break
                    } catch {
                        $downloaded = $false
                    }
                }
                if (-not $downloaded) {
                    throw "could not download uv"
                }
                $extractDir = Join-Path $toolsDir "uv-extract"
                Expand-Archive -Path $uvZip -DestinationPath $extractDir -Force
                $uvExe = Get-ChildItem -Path $extractDir -Filter "uv.exe" -Recurse | Select-Object -First 1
                if (-not $uvExe) {
                    throw "uv.exe not found in downloaded archive"
                }
                Move-Item -Path $uvExe.FullName -Destination $Uv -Force
                $uvReady = $true
            } catch {
                $uvReady = $false
            }
        }

        $pythonReady = $false
        if ($uvReady) {
            try {
                & $Uv venv --python 3.12 --seed "$HomeDir\venv"
                if ($LASTEXITCODE -eq 0) {
                    $pythonReady = $true
                }
            } catch {
                $pythonReady = $false
            }
        }

        if (-not $pythonReady) {
            $fallbackPython = $null
            foreach ($ver in @("3.12", "3.11", "3.13", "3.10")) {
                try {
                    $candidate = & py "-$ver" -c "import sys;print(sys.executable)" 2>$null
                    if ($LASTEXITCODE -eq 0 -and $candidate) {
                        $fallbackPython = $candidate.Trim()
                        break
                    }
                } catch {
                }
            }
            if (-not $fallbackPython) {
                $pythonCmds = Get-Command python -All -ErrorAction SilentlyContinue
                foreach ($cmd in $pythonCmds) {
                    if ($cmd.Source -notlike "*WindowsApps*") {
                        try {
                            $verOut = & $cmd.Source -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
                            if ($LASTEXITCODE -eq 0) {
                                $verParts = $verOut.Trim().Split(".")
                                $major = [int]$verParts[0]
                                $minor = [int]$verParts[1]
                                if ($major -eq 3 -and $minor -ge 10 -and $minor -le 13) {
                                    $fallbackPython = $cmd.Source
                                    break
                                }
                            }
                        } catch {
                        }
                    }
                }
            }
            if ($fallbackPython) {
                try {
                    & $fallbackPython -m venv "$HomeDir\venv"
                    if ($LASTEXITCODE -eq 0) {
                        $pythonReady = $true
                    }
                } catch {
                    $pythonReady = $false
                }
            }
        }

        if (-not $pythonReady) {
            Write-Host "Could not set up Python automatically. Check your internet connection and run RUN_ME.bat again. If your office network blocks GitHub, install Python 3.12 from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') and try again." -ForegroundColor Red
            exit 1
        }
    }

    # [3/4] Libraries
    Write-Host "[3/4] Checking libraries..." -ForegroundColor Cyan
    $Req = Join-Path $AppDir "requirements.txt"
    $hash = (Get-FileHash $Req -Algorithm SHA256).Hash
    $stampFile = Join-Path $HomeDir "venv\.req-hash"
    $needInstall = $true
    if (Test-Path $stampFile) {
        $oldHash = Get-Content $stampFile -Raw
        if ($oldHash.Trim() -eq $hash) {
            $needInstall = $false
        }
    }
    if ($needInstall) {
        Write-Host "Installing libraries (first time only)..." -ForegroundColor Yellow
        if (Test-Path $Uv) {
            & $Uv pip install --python $Py -r $Req
        } else {
            & $Py -m pip install --disable-pip-version-check -r $Req
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Could not download the libraries. Check your internet connection and run RUN_ME.bat again." -ForegroundColor Red
            exit 1
        }
        Set-Content -Path $stampFile -Value $hash -NoNewline
    }

    # [4/4] Start
    Write-Host "[4/4] Starting Menu Studio..." -ForegroundColor Cyan
    Write-Host "The first start also downloads the visual-check model (~600 MB) in the background; the app shows progress." -ForegroundColor Yellow

    if ($CheckOnly) {
        & $Py "$AppDir\app.py" --self-test
        exit $LASTEXITCODE
    } else {
        Set-Location $AppDir
        if ($NoBrowser) {
            & $Py "$AppDir\app.py" --no-browser
        } else {
            & $Py "$AppDir\app.py"
        }
        exit $LASTEXITCODE
    }
} catch {
    Write-Host "Unexpected problem: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
