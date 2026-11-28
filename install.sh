#!/usr/bin/env bash
# ==============================================================================
#  ⚡ Nolthira Agent Orchestrator - Universal Linux & macOS Installer
#  Usage: curl -fsSL https://raw.githubusercontent.com/ItsMeMal/NexusAgent/main/install.sh | bash
# ==============================================================================

set -e

# Terminal color codes
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
GRAY='\033[0;90m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

echo ""
printf "${CYAN}  ██╗  ██╗   ██████╗   ██╗  ████████╗  ██╗  ██╗  ██╗  ██████╗   █████╗\n"
printf "  ███╗ ██║  ██╔═══██╗  ██║  ╚══██╔══╝  ██║  ██║  ██║  ██╔══██╗  ██╔══██╗\n"
printf "  ████╗██║  ██║   ██║  ██║    ██║  ███████║  ██║  ██████╔╝  ███████║\n"
printf "  ██╔████║  ██║   ██║  ██║    ██║  ██╔══██║  ██║  ██╔══██╗  ██╔══██║\n"
printf "  ██║╚███║  ╚██████╔╝  ███████╗    ██║  ██║  ██║  ██║  ██║  ██║  ██║  ██║\n"
printf "  ╚═╝ ╚══╝   ╚═════╝   ╚══════╝    ╚═╝  ╚═╝  ╚═╝  ╚═╝  ╚═╝  ╚═╝  ╚═╝  ╚═╝\n"
printf "${NC}"
echo ""
printf "${GREEN}  ⚡ Nolthira Agent Orchestrator Installer\n${NC}"

# Detect OS
OS_NAME="$(uname -s)"
case "${OS_NAME}" in
    Linux*)     PLATFORM="Linux" ;;
    Darwin*)    PLATFORM="macOS" ;;
    *)          PLATFORM="Unknown" ;;
esac

printf "${GRAY}  Target OS: ${PLATFORM} · Home: ${HOME}/.nexus\n"
printf "  ────────────────────────────────────────────────────────────\n${NC}"
echo ""

# 1. Locate suitable Python 3.10+
PYTHON_BIN=""
for cmd in python3 python python3.13 python3.12 python3.11 python3.10; do
    if command -v "$cmd" >/dev/null 2>&1; then
        PY_VER="$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || true)"
        if [ -n "$PY_VER" ]; then
            MAJOR=$(echo "$PY_VER" | cut -d. -f1)
            MINOR=$(echo "$PY_VER" | cut -d. -f2)
            if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
                PYTHON_BIN="$cmd"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    printf "${RED}  [X] Python 3.10+ is required but not found.\n${NC}"
    printf "${YELLOW}      Please install Python 3.10+ using your package manager:\n"
    if [ "$PLATFORM" = "macOS" ]; then
        printf "        brew install python\n"
    else
        printf "        sudo apt update && sudo apt install -y python3 python3-venv python3-pip git curl\n"
    fi
    printf "${NC}\n"
    exit 1
fi

printf "${GREEN}  [OK] Found Python ($PYTHON_BIN)\n${NC}"

# 2. Verify Git
if ! command -v git >/dev/null 2>&1; then
    printf "${RED}  [X] Git is required but not found. Please install git.\n${NC}"
    exit 1
fi
printf "${GREEN}  [OK] Found Git\n${NC}"

# 3. Setup ~/.nexus home directories
NEXUS_HOME="${HOME}/.nexus"
ENGINE_DIR="${NEXUS_HOME}/engine"
BIN_DIR="${NEXUS_HOME}/bin"
VENV_DIR="${NEXUS_HOME}/venv"

printf "${CYAN}  [..] Initializing Nolthira Home at ${NEXUS_HOME}...\n${NC}"
mkdir -p "${NEXUS_HOME}"
mkdir -p "${BIN_DIR}"

# 4. Clone or update repository
if [ -d "${ENGINE_DIR}/.git" ]; then
    printf "${CYAN}  [..] Updating existing Nolthira engine...\n${NC}"
    cd "${ENGINE_DIR}"
    git sparse-checkout set nexus .skills pyproject.toml .env.example README.md 2>/dev/null || true
    git pull origin main --quiet || true
else
    printf "${CYAN}  [..] Downloading Nolthira Agent Engine from GitHub...\n${NC}"
    rm -rf "${ENGINE_DIR}"
    git clone https://github.com/ItsMeMal/NexusAgent.git "${ENGINE_DIR}" --quiet
    cd "${ENGINE_DIR}" 2>/dev/null || true
    git sparse-checkout set nexus .skills pyproject.toml .env.example README.md 2>/dev/null || true
fi

# Prune non-engine artifacts (website, tests, installers) from runtime engine directory
rm -rf "${ENGINE_DIR}/website" "${ENGINE_DIR}/tests" "${ENGINE_DIR}/install.ps1" "${ENGINE_DIR}/install.sh" "${ENGINE_DIR}/wrangler.toml"
printf "${GREEN}  [OK] Nolthira Engine ready at ${ENGINE_DIR}\n${NC}"

# 5. Create or verify virtual environment with auto-recovery
VENV_PYTHON="${VENV_DIR}/bin/python"
USE_VENV=0

# Check if venv already exists and is healthy
IS_HEALTHY_VENV=0
if [ -f "${VENV_PYTHON}" ] && "${VENV_PYTHON}" -m pip --version >/dev/null 2>&1; then
    IS_HEALTHY_VENV=1
fi

if [ "$IS_HEALTHY_VENV" -eq 0 ]; then
    printf "${CYAN}  [..] Creating isolated virtual environment...\n${NC}"
    rm -rf "${VENV_DIR}"
    
    # Try standard venv creation
    if ! "$PYTHON_BIN" -m venv "${VENV_DIR}" 2>/dev/null; then
        # Debian/Ubuntu often requires python3-venv; fallback to --without-pip + bootstrap
        "$PYTHON_BIN" -m venv --without-pip "${VENV_DIR}" 2>/dev/null || true
    fi

    # If python exists in venv, check/bootstrap pip
    if [ -f "${VENV_PYTHON}" ]; then
        if ! "${VENV_PYTHON}" -m pip --version >/dev/null 2>&1; then
            printf "${CYAN}  [..] Bootstrapping pip into virtual environment...\n${NC}"
            "${VENV_PYTHON}" -m ensurepip --default-pip 2>/dev/null || \
            curl -fsSL https://bootstrap.pypa.io/get-pip.py 2>/dev/null | "${VENV_PYTHON}" --quiet 2>/dev/null || true
        fi
    fi
fi

# Determine final execution runtime (venv vs user-level fallback)
if [ -f "${VENV_PYTHON}" ] && "${VENV_PYTHON}" -m pip --version >/dev/null 2>&1; then
    USE_VENV=1
    RUN_PYTHON="${VENV_PYTHON}"
    printf "${GREEN}  [OK] Virtual environment active at ${VENV_DIR}\n${NC}"
else
    USE_VENV=0
    RUN_PYTHON="$PYTHON_BIN"
    printf "${YELLOW}  [!] Virtual environment pip unavailable. Using user-level Python packages.\n${NC}"
fi

# 6. Install dependencies
printf "${CYAN}  [..] Installing Nolthira dependencies (httpx, rich, prompt_toolkit, ddgs, pydantic, pyautogui, pillow)...\n${NC}"
if [ "$USE_VENV" -eq 1 ]; then
    "${VENV_PYTHON}" -m pip install --quiet --upgrade pip 2>/dev/null || true
    "${VENV_PYTHON}" -m pip install --quiet -r "${ENGINE_DIR}/requirements.txt"
else
    # Handles Debian/Ubuntu PEP 668 externally-managed environment
    "$PYTHON_BIN" -m pip install --user --quiet --break-system-packages -r "${ENGINE_DIR}/requirements.txt" 2>/dev/null || \
    "$PYTHON_BIN" -m pip install --user --quiet -r "${ENGINE_DIR}/requirements.txt"
fi
printf "${GREEN}  [OK] Dependencies installed successfully.\n${NC}"

# 7. Setup default ~/.nexus/.env if not present
GLOBAL_ENV="${NEXUS_HOME}/.env"
EXAMPLE_ENV="${ENGINE_DIR}/.env.example"
if [ ! -f "${GLOBAL_ENV}" ]; then
    if [ -f "${EXAMPLE_ENV}" ]; then
        cp "${EXAMPLE_ENV}" "${GLOBAL_ENV}"
    else
        cat <<EOF > "${GLOBAL_ENV}"
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_API_KEY=your_api_key_here
NEXUS_MODEL=anthropic/claude-3.5-sonnet
NEXUS_TEMPERATURE=0.7
EOF
    fi
    printf "${GREEN}  [OK] Generated global config at ${GLOBAL_ENV}\n${NC}"
fi

# 8. Create launcher scripts in ~/.nexus/bin
LAUNCHER="${BIN_DIR}/nolthira"
cat <<EOF > "${LAUNCHER}"
#!/usr/bin/env bash
export PYTHONPATH="${ENGINE_DIR}:\${PYTHONPATH}"
exec "${RUN_PYTHON}" -m nexus.cli "\$@"
EOF
chmod +x "${LAUNCHER}"

# Keep legacy command aliases during the migration.
for legacy_name in nexus nexuss; do
    cp -f "${LAUNCHER}" "${BIN_DIR}/${legacy_name}"
    chmod +x "${BIN_DIR}/${legacy_name}"
done
printf "${GREEN}  [OK] Created CLI launcher in ${BIN_DIR}\n${NC}"

# 9. Link directly into system PATH locations so 'nexus' works INSTANTLY in any open shell
LINKED_SYSTEM=0
for sys_dir in /usr/local/bin /usr/bin; do
    if [ -d "$sys_dir" ]; then
        if [ -w "$sys_dir" ] || [ "$(id -u)" -eq 0 ]; then
            for command_name in nolthira nexus nexuss; do
                ln -sf "${LAUNCHER}" "${sys_dir}/${command_name}" 2>/dev/null
            done
            LINKED_SYSTEM=1
            printf "${GREEN}  [OK] Linked 'nolthira' to ${sys_dir} (legacy aliases retained)\n${NC}"
            break
        elif command -v sudo >/dev/null 2>&1; then
            if sudo -n ln -sf "${LAUNCHER}" "${sys_dir}/nexus" 2>/dev/null; then
                sudo ln -sf "${LAUNCHER}" "${sys_dir}/nexuss" 2>/dev/null || true
                LINKED_SYSTEM=1
                printf "${GREEN}  [OK] Linked 'nexus' to ${sys_dir} via sudo (Command immediately available)\n${NC}"
                break
            fi
        fi
    fi
done

# 10. Configure shell profile for permanent PATH fallback
SHELL_CONFIGS=()
[ -f "${HOME}/.bashrc" ] && SHELL_CONFIGS+=("${HOME}/.bashrc")
[ -f "${HOME}/.zshrc" ] && SHELL_CONFIGS+=("${HOME}/.zshrc")
[ -f "${HOME}/.profile" ] && SHELL_CONFIGS+=("${HOME}/.profile")

PATH_EXPORT="export PATH=\"${BIN_DIR}:\$PATH\""
ADDED_TO_PROFILE=0

for cfg in "${SHELL_CONFIGS[@]}"; do
    if ! grep -q ".nexus/bin" "$cfg" 2>/dev/null; then
        echo "" >> "$cfg"
        echo "# Nolthira Agent CLI" >> "$cfg"
        echo "$PATH_EXPORT" >> "$cfg"
        ADDED_TO_PROFILE=1
    fi
done

if [ "$ADDED_TO_PROFILE" -eq 1 ]; then
    printf "${GREEN}  [OK] Added ~/.nexus/bin to shell profile (PATH)\n${NC}"
fi

echo ""
printf "  ────────────────────────────────────────────────────────────\n"
printf "${GREEN}  ✨ Nolthira Agent Orchestrator has been successfully installed!\n${NC}"
echo ""
printf "${WHITE}  🚀 Getting Started:\n${NC}"
printf "${GRAY}     1. Configure your API key:\n${NC}"
printf "${CYAN}        nano ${GLOBAL_ENV}\n${NC}"
printf "${GRAY}     2. Launch Nolthira from any folder:\n${NC}"
printf "${YELLOW}        nolthira\n${NC}"
printf "${GRAY}        (legacy alias: nexus)\n${NC}"
echo ""
