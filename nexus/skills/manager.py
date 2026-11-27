from pathlib import Path
from typing import List, Dict, Any, Optional
import re
import os


class Skill:
    def __init__(self, name: str, description: str, content: str, file_path: Path):
        self.name = name
        self.description = description
        self.content = content
        self.file_path = file_path


def _extract_skill_description(text: str) -> str:
    """Extract single-line or multiline YAML frontmatter / heading description cleanly."""
    lines = text.splitlines()
    desc = ""

    if lines and lines[0].strip() == "---":
        in_desc = False
        desc_parts: List[str] = []
        for line in lines[1:35]:
            stripped = line.strip()
            if stripped == "---":
                break
            if not in_desc:
                if line.lower().startswith("description:"):
                    raw_val = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if raw_val in (">", "|", ">-", "|-", ""):
                        in_desc = True
                    else:
                        desc = raw_val
                        break
            else:
                # End multiline YAML value at next top-level key
                if line and not line[0].isspace() and ":" in line:
                    break
                if stripped:
                    desc_parts.append(stripped)
        if not desc and desc_parts:
            desc = " ".join(desc_parts)

    if not desc or desc in (">", "|"):
        for line in lines[:20]:
            s = line.strip()
            if s.startswith(("Description:", "> Description:")):
                desc = s.split(":", 1)[1].strip()
                break
            elif s.startswith("# ") and not desc:
                desc = s.lstrip("# ").strip()

    desc = re.sub(r"\s+", " ", desc or "").strip()
    return desc if desc else "No description"


def _default_skill_search_paths() -> List[Path]:
    """
    Return all candidate directories to search for skills, in priority order:
    1. Local workspace .skills/ (project-specific)
    2. NEXUS_SKILLS_DIR env override
    3. ~/.nexus/skills/ (Nexus global)
    4. ~/.agents/skills/ (shared agents convention — Linux/Mac/Windows)
    5. ~/.agents/nexus/skills/ (Nexus sub-namespace)
    6. Codebase .skills/ (bundled)
    """
    home = Path.home()
    nexus_home = home / ".nexus"
    agents_home = home / ".agents"
    codebase_root = Path(__file__).resolve().parent.parent.parent

    candidates: List[Optional[Path]] = [
        Path.cwd() / ".skills",
        Path(os.getenv("NEXUS_SKILLS_DIR", "")) if os.getenv("NEXUS_SKILLS_DIR") else None,
        nexus_home / "skills",
        agents_home / "skills",
        agents_home / "nexus" / "skills",
        codebase_root / ".skills",  # bundled core skills (incl. vercel-labs/agent-skills)
    ]

    # Auto-discover skills bundled inside plugins (e.g., plugins/superpowers/skills)
    for plugin_root in (Path.cwd() / "plugins", nexus_home / "plugins", codebase_root / "plugins"):
        if plugin_root.exists() and plugin_root.is_dir():
            for p_sub in sorted(plugin_root.iterdir()):
                if p_sub.is_dir() and (p_sub / "skills").is_dir():
                    candidates.append(p_sub / "skills")
    # Deduplicate while preserving order
    seen = set()
    result = []
    for p in candidates:
        if p and str(p) not in seen:
            seen.add(str(p))
            result.append(p)
    return result


class SkillManager:
    def __init__(self, skills_dir: Path, extra_dirs: Optional[List[Path]] = None):
        """
        skills_dir     : Primary writable skills directory (where create_skill saves to).
        extra_dirs     : Additional read-only skill directories to scan.
                         If None, automatically discovers all standard paths.
        """
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)

        if extra_dirs is not None:
            self._extra_dirs = extra_dirs
        else:
            # Auto-discover all standard paths except skills_dir (avoid double-loading)
            self._extra_dirs = [
                p for p in _default_skill_search_paths()
                if p.resolve() != self.skills_dir.resolve()
            ]

    def all_search_dirs(self) -> List[Path]:
        """Return all directories that will be scanned, primary first."""
        return [self.skills_dir] + self._extra_dirs

    def load_all_skills(self) -> List[Skill]:
        """Load skills from all configured directories. Primary dir takes precedence (deduped by name)."""
        seen_names: Dict[str, bool] = {}
        skills: List[Skill] = []

        for directory in self.all_search_dirs():
            if not directory.exists():
                continue
            # Support flat *.md skills and subdirectory SKILL.md convention without picking up AGENTS.md/README.md
            md_files: List[Path] = []
            md_files.extend(directory.glob("*.md"))
            for sub in sorted(directory.iterdir()):
                if not sub.is_dir():
                    continue
                skill_md = sub / "SKILL.md"
                if skill_md.exists():
                    md_files.append(skill_md)
                else:
                    named_md = sub / f"{sub.name}.md"
                    if named_md.exists():
                        md_files.append(named_md)

            for file in sorted(md_files):
                try:
                    text = file.read_text(encoding="utf-8")
                    desc = _extract_skill_description(text)

                    # Skill name: use parent dir name for SKILL.md, otherwise file stem
                    if file.name == "SKILL.md":
                        skill_name = file.parent.name
                    else:
                        skill_name = file.stem

                    # Deduplicate: primary dir wins
                    if skill_name in seen_names:
                        continue
                    seen_names[skill_name] = True

                    skills.append(Skill(
                        name=skill_name,
                        description=desc,
                        content=text,
                        file_path=file,
                    ))
                except Exception:
                    continue

        return skills

    def get_skill(self, name: str) -> Optional[Skill]:
        """Search all directories for a skill by name (exact, then normalized fallback)."""
        clean = (name or "").strip()
        if not clean:
            return None
        for directory in self.all_search_dirs():
            for candidate in [
                directory / f"{clean}.md",
                directory / clean / "SKILL.md",
                directory / clean / f"{clean}.md",
            ]:
                if candidate.exists():
                    try:
                        text = candidate.read_text(encoding="utf-8")
                        return Skill(name=clean, description="", content=text, file_path=candidate)
                    except Exception:
                        continue
        # Normalized case-insensitive / hyphen-underscore fallback
        norm_target = re.sub(r"[-_\s]+", "", clean.lower())
        for skill in self.load_all_skills():
            if re.sub(r"[-_\s]+", "", skill.name.lower()) == norm_target:
                return skill
        return None

    def match_skills(self, query: str, top_k: int = 5) -> List[Skill]:
        """Return top skills matching query keywords (with Indonesian/domain synonym expansion)."""
        raw_tokens = set(re.findall(r"[a-z0-9]{2,}", (query or "").lower()))
        stopwords = {
            "the", "and", "for", "with", "this", "that", "from", "into", "can", "you",
            "buat", "buatkan", "bikin", "bikinin", "yang", "dan", "untuk", "ini", "itu",
            "nya", "bisa", "tolong", "please", "make", "create", "build", "use", "using",
            "pakai", "pake", "dong", "bro", "brother", "nih", "gue", "gw", "aku", "mau",
            "bebas", "full", "your", "skills", "skill",
        }
        tokens = {t for t in raw_tokens if len(t) >= 3 and t not in stopwords}

        # Bilingual & domain synonym expansion so prompts like 'website portofolio interaktif' match frontend skills
        synonym_groups = [
            ({"portofolio", "porto", "portfolio", "website", "web", "situs", "halaman", "landing", "aplikasi", "tampilan", "ui", "ux", "frontend", "design", "desain", "css", "html", "tailwind"},
             {"web", "frontend", "ui", "ux", "design", "react", "composition", "guidelines", "impeccable", "shadcn", "tailwind"}),
            ({"interaktif", "interactive", "animasi", "animation", "motion", "gerak", "transisi", "transition"},
             {"transitions", "view", "kinetic", "animation", "impeccable", "frontend"}),
            ({"react", "nextjs", "next", "vite", "tsx", "jsx", "komponen", "component"},
             {"react", "composition", "vercel", "best", "practices", "transitions"}),
            ({"deploy", "hosting", "vercel", "publish"},
             {"deploy", "vercel"}),
            ({"bug", "error", "fix", "perbaiki", "rusak", "debug", "gagal"},
             {"debugging", "systematic"}),
            ({"test", "testing", "uji", "verifikasi", "tdd"},
             {"test", "tdd", "verification"}),
            ({"rencana", "plan", "arsitektur", "blueprint", "brainstorm"},
             {"brainstorming", "writing", "plans"}),
            ({"git", "commit", "branch", "worktree"},
             {"git", "worktrees", "branch"}),
        ]
        expanded = set(tokens)
        for triggers, adds in synonym_groups:
            if raw_tokens & triggers:
                expanded |= adds
        if not expanded:
            return []

        scored: List[tuple[int, Skill]] = []
        meta_gate_skills = {"using-superpowers", "run-workflow", "swarm_monitor", "swarm_pane"}
        explicit_plan_or_brainstorm = bool(raw_tokens & {"plan", "rencana", "brainstorm", "brainstorming", "superpowers"})
        for skill in self.load_all_skills():
            if skill.name in meta_gate_skills:
                continue
            if skill.name == "brainstorming" and not explicit_plan_or_brainstorm:
                continue
            name_low = skill.name.lower()
            desc_low = (skill.description or "").lower()
            name_words = set(re.findall(r"[a-z0-9]{2,}", name_low))
            desc_words = set(re.findall(r"[a-z0-9]{3,}", desc_low))
            score = 0
            for tok in expanded:
                if tok in name_words or tok in name_low:
                    score += 4
                elif tok in desc_words:
                    score += 2
            # Small tie-breaker boost for bundled repo / superpowers skills
            fp_low = str(skill.file_path).lower()
            if score > 0 and (".skills" in fp_low or "superpowers" in fp_low):
                score += 1
            if score >= 3:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:top_k]]

    def save_skill(self, name: str, description: str, content: str) -> Path:
        """Save a new skill to the primary (writable) skills directory."""
        clean_name = re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-").lower()
        file_path = self.skills_dir / f"{clean_name}.md"
        full_text = f"# Skill: {clean_name}\nDescription: {description}\n\n{content}\n"
        file_path.write_text(full_text, encoding="utf-8")
        return file_path

    def get_skills_summary(self, compact: bool = False, query: str = "", max_chars: int = 4500) -> str:
        skills = self.load_all_skills()
        if not skills:
            dirs = [str(d) for d in self.all_search_dirs()]
            return f"No skills found. Searched: {', '.join(dirs)}"

        if query and query.strip():
            q = query.strip().lower()
            skills = [s for s in skills if q in s.name.lower() or q in (s.description or "").lower()]
            if not skills:
                return f"No skills match query '{query}'."

        if not compact:
            lines = [f"Available Skills ({len(skills)}):"]
            for s in skills:
                source = str(s.file_path.parent)
                lines.append(f"- **{s.name}**: {s.description}  _(from {source})_")
            return "\n".join(lines)

        # Compact system-prompt catalog: bundled/plugin skills first, truncated cleanly to keep token budget lean
        total = len(skills)
        def _priority_key(s: Skill):
            fp = str(s.file_path).lower()
            is_bundled = (str(self.skills_dir).lower() in fp or "superpowers" in fp or "nexusagentcliv2" in fp)
            return (not is_bundled, s.name.lower())

        ordered = sorted(skills, key=_priority_key)
        lines = [f"Available Skills ({total} total — call `list_skills(query)` to search or `read_skill(name)` to load):"]
        used_chars = len(lines[0])
        shown = 0
        for s in ordered:
            short_desc = s.description if len(s.description) <= 72 else s.description[:69] + "..."
            entry = f"- **{s.name}**: {short_desc}"
            if used_chars + len(entry) + 1 > max_chars and shown >= 15:
                break
            lines.append(entry)
            used_chars += len(entry) + 1
            shown += 1

        if shown < total:
            lines.append(f"... (+{total - shown} more skills; call `list_skills(query='keyword')` to discover them)")
        return "\n".join(lines)

    def get_search_paths_summary(self) -> str:
        """Return human-readable list of all skill search paths and their status."""
        lines = []
        for d in self.all_search_dirs():
            exists = d.exists()
            count = len(list(d.glob("*.md")) + list(d.glob("*/SKILL.md"))) if exists else 0
            status = f"✓ {count} skill(s)" if exists else "✗ not found"
            lines.append(f"  {status}  →  {d}")
        return "\n".join(lines)
