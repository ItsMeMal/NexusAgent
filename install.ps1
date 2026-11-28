# ==============================================================================
#  ⚡ Nolthira Agent Orchestrator - One-Line Windows Installer
#  Usage: irm https://raw.githubusercontent.com/ItsMeMal/NolthiraAgent/main/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  ███╗   ██╗  ██████╗  ██╗      ████████╗ ██╗  ██╗ ╔══════╗ ██████╗   █████╗ " -ForegroundColor Cyan
Write-Host "  ████╗  ██║ ██╔═══██╗ ██║      ╚══██╔══╝ ██║  ██║ ╚══╗╔══╝ ██╔══██╗ ██╔══██╗" -ForegroundColor Cyan
Write-Host "  ██╔██╗ ██║ ██║   ██║ ██║         ██║    ███████║    ║║    ██████╔╝ ███████║" -ForegroundColor Cyan
Write-Host "  ██║╚██╗██║ ██║   ██║ ██║         ██║    ██╔══██║    ║║    ██╔══██╗ ██╔══██║" -ForegroundColor Cyan
Write-Host "  ██║ ╚████║ ╚██████╔╝ ███████╗    ██║    ██║  ██║ ╔══╝╚══╗ ██║  ██║ ██║  ██║" -ForegroundColor Cyan
Write-Host "  ╚═╝  ╚═══╝  ╚═════╝  ╚══════╝    ╚═╝    ╚═╝  ╚═╝ ╚══════╝ ╚═╝  ╚═╝ ╚═╝  ╚═╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  ⚡ Nolthira Agent Orchestrator Installer" -ForegroundColor Green
Write-Host "  Target OS: Windows · Home: $env:USERPROFILE\.nolthira" -ForegroundColor DarkGray
Write-Host "  ────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host ""

# 1. Verify Python installation
$pythonCmd = $null
if (Get-Command python -ErrorAction SilentlyContinue) {
    $pythonCmd = "python"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $pythonCmd = "py"
} elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
    $pythonCmd = "python3"
}

if (-not $pythonCmd) {
    Write-Host "  [X] Python 3.10+ is required but not found." -ForegroundColor Red
    Write-Host "      Please install Python from https://www.python.org/ or Microsoft Store." -ForegroundColor Yellow
    exit 1
}

# Verify Python version >= 3.10
$pyVer = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
$pyMajor = [int]$pyVer.Split(".")[0]
$pyMinor = [int]$pyVer.Split(".")[1]

if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 10)) {
    Write-Host "  [X] Python version is $pyVer. Nolthira requires Python 3.10 or higher." -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] Found Python $pyVer ($pythonCmd)" -ForegroundColor Green

# 2. Verify Git installation
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "  [X] Git is required but not found." -ForegroundColor Red
    Write-Host "      Please install Git from https://git-scm.com/download/win" -ForegroundColor Yellow
    exit 1
}
Write-Host "  [OK] Found Git" -ForegroundColor Green

# 3. Migrate legacy ~/.nexus into canonical ~/.nolthira.
$legacyHome = Join-Path $env:USERPROFILE ".nexus"
$nolthiraHome = Join-Path $env:USERPROFILE ".nolthira"

function Move-LegacyHomeEntries {
    param([string]$Source, [string]$Destination)
    New-Item -ItemType Directory -Force -Path $Destination | Out-Null
    foreach ($entry in Get-ChildItem -LiteralPath $Source -Force) {
        $target = Join-Path $Destination $entry.Name
        $isRealDirectory = $entry.PSIsContainer -and (($entry.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0)
        if (Test-Path -LiteralPath $target) {
            if ($isRealDirectory -and (Test-Path -LiteralPath $target -PathType Container) -and $entry.Name -notin @("engine", "venv", ".git")) {
                Move-LegacyHomeEntries -Source $entry.FullName -Destination $target
            }
            continue
        }
        Move-Item -LiteralPath $entry.FullName -Destination $target
    }
    if ((Get-ChildItem -LiteralPath $Source -Force | Measure-Object).Count -eq 0) {
        Remove-Item -LiteralPath $Source -Force
    }
}

if (Test-Path -LiteralPath $legacyHome -PathType Container) {
    if (-not (Test-Path -LiteralPath $nolthiraHome)) {
        Move-Item -LiteralPath $legacyHome -Destination $nolthiraHome
    } else {
        Write-Host "  [..] Merging legacy .nexus data into .nolthira without overwriting existing files..." -ForegroundColor Cyan
        Move-LegacyHomeEntries -Source $legacyHome -Destination $nolthiraHome
        if (Test-Path -LiteralPath $legacyHome) {
            Write-Warning "Some conflicting legacy data remains in $legacyHome; it was kept as a backup."
        }
    }
}

$engineDir = Join-Path $nolthiraHome "engine"
$binDir = Join-Path $nolthiraHome "bin"
$venvDir = Join-Path $nolthiraHome "venv"
Write-Host "  [..] Initializing Nolthira Home at $nolthiraHome..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $nolthiraHome | Out-Null
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

# 4. Clone or update repository
if (Test-Path (Join-Path $engineDir ".git")) {
    Write-Host "  [..] Updating existing Nolthira engine..." -ForegroundColor Cyan
    Push-Location $engineDir
    git remote set-url origin https://github.com/ItsMeMal/NolthiraAgent.git
    if ($LASTEXITCODE -ne 0) {
        git remote add origin https://github.com/ItsMeMal/NolthiraAgent.git
    }
    git sparse-checkout set --no-cone /nexus/ /.skills/ /pyproject.toml /.env.example /README.md /requirements.txt 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Failed to configure sparse checkout." }
    git fetch origin main --quiet
    if ($LASTEXITCODE -ne 0) { throw "Failed to fetch NolthiraAgent from GitHub." }
    git pull --ff-only origin main --quiet
    if ($LASTEXITCODE -ne 0) { throw "Failed to fast-forward the existing Nolthira engine." }
    Pop-Location
} else {
    Write-Host "  [..] Downloading Nolthira Agent Engine from GitHub..." -ForegroundColor Cyan
    if (Test-Path $engineDir) {
        Remove-Item -Recurse -Force $engineDir
    }
    git clone https://github.com/ItsMeMal/NolthiraAgent.git $engineDir --quiet
    Push-Location $engineDir
    git sparse-checkout set --no-cone /nexus/ /.skills/ /pyproject.toml /.env.example /README.md /requirements.txt 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Failed to configure sparse checkout for a fresh installation." }
    Pop-Location
}

# Prune non-engine artifacts from runtime engine directory
$pruneTargets = @("website", "tests", "install.sh", "install.ps1", "wrangler.toml")
foreach ($target in $pruneTargets) {
    $p = Join-Path $engineDir $target
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
    }
}
Write-Host "  [OK] Nolthira Engine ready at $engineDir" -ForegroundColor Green

# 5. Create or verify virtualenv
$venvPython = Join-Path (Join-Path $venvDir "Scripts") "python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "  [..] Creating isolated virtual environment..." -ForegroundColor Cyan
    & $pythonCmd -m venv $venvDir
}

# 6. Install dependencies
Write-Host "  [..] Installing Nolthira dependencies (httpx, rich, prompt_toolkit, ddgs, pydantic, pyautogui, pillow)..." -ForegroundColor Cyan
$reqFile = Join-Path $engineDir "requirements.txt"
& $venvPython -m pip install --quiet --upgrade pip
& $venvPython -m pip install --quiet -r $reqFile
Write-Host "  [OK] Dependencies installed successfully." -ForegroundColor Green

# 7. Setup default ~/.nolthira/.env if not present
$globalEnv = Join-Path $nolthiraHome ".env"
$exampleEnv = Join-Path $engineDir ".env.example"
if (-not (Test-Path $globalEnv)) {
    if (Test-Path $exampleEnv) {
        Copy-Item $exampleEnv $globalEnv
    } else {
        @"
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_API_KEY=your_api_key_here
NEXUS_MODEL=anthropic/claude-3.5-sonnet
NEXUS_TEMPERATURE=0.7
"@ | Set-Content $globalEnv -Encoding UTF8
    }
    Write-Host "  [OK] Generated global config at $globalEnv" -ForegroundColor Green
}

# 8. Create launcher scripts in ~/.nolthira/bin
$launcherCmd = Join-Path $binDir "nolthira.cmd"
$launcherPs1 = Join-Path $binDir "nolthira.ps1"

@"
@echo off
"$venvPython" -m nexus.cli %*
"@ | Set-Content $launcherCmd -Encoding ASCII

@"
& "$venvPython" -m nexus.cli @args
"@ | Set-Content $launcherPs1 -Encoding UTF8

# Keep legacy commands working while users migrate to "nolthira".
foreach ($legacyName in @("nexus", "nexuss")) {
    Copy-Item $launcherCmd (Join-Path $binDir "${legacyName}.cmd") -Force
    Copy-Item $launcherPs1 (Join-Path $binDir "${legacyName}.ps1") -Force
}
Write-Host "  [OK] Created CLI launcher in $binDir" -ForegroundColor Green

# 9. Add ~/.nolthira/bin to User PATH permanently
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$binDir*") {
    $newPath = "$binDir;$userPath"
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "  [OK] Added $binDir to User Environment PATH" -ForegroundColor Green
}

# Update current session PATH immediately
if ($env:Path -notlike "*$binDir*") {
    $env:Path = "$binDir;$env:Path"
}

# 10. Also link to standard pre-existing PATH directories for immediate command resolution
$standardDirs = @(
    (Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps"),
    (Join-Path (Split-Path (Get-Command $pythonCmd).Source) "Scripts")
)

foreach ($targetDir in $standardDirs) {
    if (Test-Path $targetDir) {
        try {
            foreach ($commandName in @("nolthira", "nexus", "nexuss")) {
                Copy-Item (Join-Path $binDir "${commandName}.cmd") (Join-Path $targetDir "${commandName}.cmd") -Force -ErrorAction SilentlyContinue
                Copy-Item (Join-Path $binDir "${commandName}.ps1") (Join-Path $targetDir "${commandName}.ps1") -Force -ErrorAction SilentlyContinue
            }
            Write-Host "  [OK] Linked 'nolthira' to $targetDir (legacy aliases retained)" -ForegroundColor Green
            break
        } catch {}
    }
}

Write-Host ""
Write-Host "  ────────────────────────────────────────────────────────────" -ForegroundColor DarkGray
Write-Host "  ✨ Nolthira Agent Orchestrator has been successfully installed!" -ForegroundColor Green
Write-Host ""
Write-Host "  🚀 Getting Started:" -ForegroundColor White
Write-Host "     1. Configure your API key:" -ForegroundColor DarkGray
Write-Host "        notepad $globalEnv" -ForegroundColor Cyan
Write-Host "     2. Launch Nolthira from any folder:" -ForegroundColor DarkGray
Write-Host "        nolthira" -ForegroundColor Yellow
Write-Host ""
