import re
from pathlib import Path
from typing import Tuple, List, Optional
from enum import Enum
from ..config import config

class RiskLevel(Enum):
    SAFE = "SAFE"
    SUSPICIOUS = "SUSPICIOUS"
    DANGEROUS = "DANGEROUS"

CRITICAL_PATTERNS = [
    r"\brm\s+-[rf]{1,2}\s+[/~]",                   # rm -rf / or rm -rf ~
    r"\brmdir\s+/[sq]\s+[a-zA-Z]:\\",              # rmdir /s /q C:\
    r"\bdel\s+/[sfq]{1,3}\s+[a-zA-Z]:\\",          # del /s /f /q C:\
    r"\bformat\s+[a-zA-Z]:",                       # format C:
    r"\bmkfs\b",                                   # filesystem format
    r"\bdd\s+if=",                                 # raw disk writes
    r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:",   # fork bomb
    r"\bdrop\s+database\b",                         # drop database
    r"\btruncate\s+table\b",                       # truncate table
    r"\bshutdown\s+[/s|/r]",                       # system shutdown
    r"\breboot\b",                                 # reboot
    r">\s*/dev/sd[a-z]",                           # raw disk redirection
    r">\s*\\\\.\\PhysicalDrive",                   # raw physical drive access
]

SUSPICIOUS_PATTERNS = [
    r"\brm\s+-[rf]",                               # general recursive delete
    r"\bdel\s+/[sq]",
    r"\bchmod\s+777\b",
    r"\bcurl\s+.*\|\s*(bash|sh|powershell|pwsh)",  # pipe to shell
    r"\bwget\s+.*\|\s*(bash|sh|powershell|pwsh)",
    r"\bgit\s+reset\s+--hard\b",                   # hard reset
    r"\bgit\s+clean\s+-[xfd]",                     # git clean
    r"\bInvoke-Expression\b",                      # powershell iex
    r"\biex\s*\(",
    r"\bpowershell\s+-[eE][ncod]*",                 # encoded powershell
]

SECRET_PATTERNS = [
    r"(^|[/\\])\.env($|\..*)",                     # .env, .env.local, .env.production
    r"(^|[/\\])id_rsa($|\.pub)?",                  # ssh private keys
    r"(^|[/\\])id_ed25519($|\.pub)?",
    r"(^|[/\\])\.ssh[/\\]",                        # .ssh folder
    r"\.pem$",                                     # certificates & private keys
    r"\.key$",
    r"\.pfx$",
    r"(^|[/\\])\.aws[/\\]credentials",             # aws credentials
    r"(^|[/\\])\.git[/\\]config",                  # git credentials
]

JAILBREAK_PATTERNS = [
    r"\bignore\s+(all\s+)?(previous|prior)\s+(instructions|prompts|rules)\b",
    r"\bdisregard\s+(all\s+)?(previous|prior)\s+(instructions|prompts|rules)\b",
    r"\bbypass\s+(all\s+)?(safety|guardrails|filters|security)\b",
    r"\byou\s+are\s+now\s+(DAN|unrestricted|jailbroken|evil)\b",
    r"\bdeveloper\s+mode\s+enabled\b",
    r"\boutput\s+(the\s+entire\s+)?system\s+prompt\b",
    r"\bprint\s+(the\s+entire\s+)?system\s+prompt\b",
    r"\bexfiltrate\b",
    r"\bprint\s+(your\s+)?api[_-]?key\b",
    r"\breturn\s+(the\s+)?\.env\s+file\b",
]

class SecurityGuard:
    """Security guardrails, command risk assessment, path sandboxing, and prompt safety."""

    @staticmethod
    def assess_command_risk(cmd: str) -> Tuple[RiskLevel, str]:
        cmd_clean = cmd.strip()

        for pattern in CRITICAL_PATTERNS:
            if re.search(pattern, cmd_clean, re.IGNORECASE):
                return RiskLevel.DANGEROUS, f"Critical destructive pattern detected: {pattern}"

        for pattern in SUSPICIOUS_PATTERNS:
            if re.search(pattern, cmd_clean, re.IGNORECASE):
                return RiskLevel.SUSPICIOUS, f"Potentially disruptive command pattern: {pattern}"

        return RiskLevel.SAFE, "Command passes baseline safety heuristics."

    @staticmethod
    def is_path_safe(path: Path, root_dir: Path) -> bool:
        """Validate that path does not escape into critical OS directories."""
        try:
            resolved = path.resolve()
            # Block system OS directories
            forbidden_prefixes = [
                "C:\\Windows", 
                "C:\\Program Files", 
                "C:\\Program Files (x86)",
                "/etc", 
                "/bin", 
                "/sbin", 
                "/usr", 
                "/sys", 
                "/proc", 
                "/dev",
                "/root"
            ]
            for f in forbidden_prefixes:
                if str(resolved).lower().startswith(f.lower()):
                    return False
            return True
        except Exception:
            return False

    @staticmethod
    def is_secret_path(path: Path) -> bool:
        """Check if path targets sensitive secrets or credentials."""
        path_str = str(path).replace("\\", "/")
        # Allow .env.example
        if path_str.endswith(".env.example"):
            return False
            
        for pattern in SECRET_PATTERNS:
            if re.search(pattern, path_str, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def inspect_text_safety(text: str) -> Tuple[bool, Optional[str]]:
        """Inspect prompt or tool content for injection or jailbreak indicators."""
        if not text:
            return True, None
            
        for pattern in JAILBREAK_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return False, f"Potential injection or jailbreak pattern detected: '{pattern}'"
                
        return True, None
