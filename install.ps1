# ==============================================================================
#  ⚡ Nolthira Agent Orchestrator - One-Line Windows Installer
#  Usage: irm https://raw.githubusercontent.com/ItsMeMal/NexusAgent/main/install.ps1 | iex
# ==============================================================================

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "  ██╗  ██╗   ██████╗   ██╗  ████████╗  ██╗  ██╗  ██╗  ██████╗   █████╗" -ForegroundColor Cyan
Write-Host "  ███╗ ██║  ██╔═══██╗  ██║  ╚══██╔══╝  ██║  ██║  ██║  ██╔══██╗  ██╔══██╗" -ForegroundColor Cyan
Write-Host "  ████╗██║  ██║   ██║  ██║    ██║  ███████║  ██║  ██████╔╝  ███████║" -ForegroundColor Cyan
Write-Host "  ██╔████║  ██║   ██║  ██║    ██║  ██╔══██║  ██║  ██╔══██╗  ██╔══██║" -ForegroundColor Cyan
Write-Host "  ██║╚███║  ╚██████╔╝  ███████╗    ██║  ██║  ██║  ██║  ██║  ██║  ██║  ██║" -ForegroundColor Cyan
Write-Host "  ╚═╝ ╚══╝   ╚═════╝   ╚══════╝    ╚═╝  ╚═╝  ╚═╝  ╚═╝  ╚═╝  ╚═╝  ╚═╝  ╚═╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  ⚡ Nolthira Agent Orchestrator Installer" -ForegroundColor Green
Write-Host "  Target OS: Windows · Home: $env:USERPROFILE\.nexus" -ForegroundColor DarkGray
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

# 3. Setup ~/.nexus home directories
$nexusHome = Join-Path $env:USERPROFILE ".nexus"
$engineDir = Join-Path $nexusHome "engine"
$binDir = Join-Path $nexusHome "bin"
$venvDir = Join-Path $nexusHome "venv"

Write-Host "  [..] Initializing Nolthira Home at $nexusHome..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $nexusHome | Out-Null
New-Item -ItemType Directory -Force -Path $binDir | Out-Null

# 4. Clone or update repository
if (Test-Path (Join-Path $engineDir ".git")) {
    Write-Host "  [..] Updating existing Nolthira engine..." -ForegroundColor Cyan
    Push-Location $engineDir
    git sparse-checkout set nexus .skills pyproject.toml .env.example README.md requirements.txt 2>$null
    git pull origin main --quiet
    Pop-Location
} else {
    Write-Host "  [..] Downloading Nolthira Agent Engine from GitHub..." -ForegroundColor Cyan
    if (Test-Path $engineDir) {
        Remove-Item -Recurse -Force $engineDir
    }
    git clone https://github.com/ItsMeMal/NexusAgent.git $engineDir --quiet
    Push-Location $engineDir
    git sparse-checkout set nexus .skills pyproject.toml .env.example README.md requirements.txt 2>$null
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

# 7. Setup default ~/.nexus/.env if not present
$globalEnv = Join-Path $nexusHome ".env"
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

# 8. Create launcher scripts in ~/.nexus/bin
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

# 9. Add ~/.nexus/bin to User PATH permanently
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
Write-Host "        (legacy alias: nexus)" -ForegroundColor DarkGray
Write-Host ""
