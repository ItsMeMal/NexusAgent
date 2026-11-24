#!/usr/bin/env bash
# ==============================================================================
#  ⚡ Nexus Agent Orchestrator - One-Line Linux & macOS Installer
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
printf "${CYAN}  ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗\n"
printf "  ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝\n"
printf "  ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗\n"
printf "  ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║\n"
printf "  ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║\n"
printf "  ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝\n${NC}"
echo ""
printf "${GREEN}  ⚡ Nexus Agent Orchestrator Installer\n${NC}"

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

# 1. Verify Python 3.10+
PYTHON_BIN=""
for cmd in python3 python python3.12 python3.11 python3.10; do
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
        printf "        sudo apt update && sudo apt install -y python3 python3-venv python3-pip git\n"
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

# 3. Setup ~/.nexus directories
NEXUS_HOME="${HOME}/.nexus"
ENGINE_DIR="${NEXUS_HOME}/engine"
BIN_DIR="${NEXUS_HOME}/bin"
VENV_DIR="${NEXUS_HOME}/venv"

printf "${CYAN}  [..] Initializing Nexus Home at ${NEXUS_HOME}...\n${NC}"
mkdir -p "${NEXUS_HOME}"
mkdir -p "${BIN_DIR}"

# 4. Clone or update repository
if [ -d "${ENGINE_DIR}/.git" ]; then
    printf "${CYAN}  [..] Updating existing Nexus engine...\n${NC}"
    cd "${ENGINE_DIR}"
    git pull origin main --quiet || true
else
    printf "${CYAN}  [..] Downloading Nexus Agent Engine from GitHub...\n${NC}"
    rm -rf "${ENGINE_DIR}"
    git clone https://github.com/ItsMeMal/NexusAgent.git "${ENGINE_DIR}" --quiet
fi
printf "${GREEN}  [OK] Nexus Engine ready at ${ENGINE_DIR}\n${NC}"

# 5. Create or verify virtual environment
VENV_PYTHON="${VENV_DIR}/bin/python"
if [ ! -f "${VENV_PYTHON}" ]; then
    printf "${CYAN}  [..] Creating isolated virtual environment...\n${NC}"
    "$PYTHON_BIN" -m venv "${VENV_DIR}"
fi

# 6. Install dependencies
printf "${CYAN}  [..] Installing Nexus dependencies (httpx, rich, prompt_toolkit, ddgs, pydantic)...\n${NC}"
"${VENV_DIR}/bin/pip" install --quiet --upgrade pip
"${VENV_DIR}/bin/pip" install --quiet -r "${ENGINE_DIR}/requirements.txt"
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
LAUNCHER="${BIN_DIR}/nexus"
cat <<EOF > "${LAUNCHER}"
#!/usr/bin/env bash
export PYTHONPATH="${ENGINE_DIR}:\${PYTHONPATH}"
exec "${VENV_DIR}/bin/python" -m nexus.cli "\$@"
EOF
chmod +x "${LAUNCHER}"

# Create 'nexuss' alias
cp -f "${LAUNCHER}" "${BIN_DIR}/nexuss"
chmod +x "${BIN_DIR}/nexuss"
printf "${GREEN}  [OK] Created CLI launcher in ${BIN_DIR}\n${NC}"

# 9. Configure shell profile for PATH
SHELL_CONFIGS=()
[ -f "${HOME}/.bashrc" ] && SHELL_CONFIGS+=("${HOME}/.bashrc")
[ -f "${HOME}/.zshrc" ] && SHELL_CONFIGS+=("${HOME}/.zshrc")
[ -f "${HOME}/.profile" ] && SHELL_CONFIGS+=("${HOME}/.profile")

PATH_EXPORT="export PATH=\"${BIN_DIR}:\$PATH\""
ADDED_TO_PROFILE=0

for cfg in "${SHELL_CONFIGS[@]}"; do
    if ! grep -q ".nexus/bin" "$cfg" 2>/dev/null; then
        echo "" >> "$cfg"
        echo "# Nexus Agent CLI" >> "$cfg"
        echo "$PATH_EXPORT" >> "$cfg"
        ADDED_TO_PROFILE=1
    fi
done

if [ "$ADDED_TO_PROFILE" -eq 1 ]; then
    printf "${GREEN}  [OK] Added ~/.nexus/bin to shell profile (PATH)\n${NC}"
fi

echo ""
printf "  ────────────────────────────────────────────────────────────\n"
printf "${GREEN}  ✨ Nexus Agent Orchestrator has been successfully installed!\n${NC}"
echo ""
printf "${WHITE}  🚀 Getting Started:\n${NC}"
printf "${GRAY}     1. Configure your API key:\n${NC}"
printf "${CYAN}        nano ${GLOBAL_ENV}\n${NC}"
printf "${GRAY}     2. Launch Nexus from any folder:\n${NC}"
printf "${YELLOW}        export PATH=\"${BIN_DIR}:\$PATH\"\n"
printf "        nexus\n${NC}"
echo ""
