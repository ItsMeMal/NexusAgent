from pathlib import Path
from typing import List, Dict, Any, Optional
import re

class Skill:
    def __init__(self, name: str, description: str, content: str, file_path: Path):
        self.name = name
        self.description = description
        self.content = content
        self.file_path = file_path

class SkillManager:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def load_all_skills(self) -> List[Skill]:
        skills = []
        for file in self.skills_dir.glob("*.md"):
            try:
                text = file.read_text(encoding="utf-8")
                # Parse description if present in header or frontmatter
                desc = "No description provided"
                lines = text.splitlines()
                for line in lines[:10]:
                    if line.startswith("Description:") or line.startswith("> Description:"):
                        desc = line.split(":", 1)[1].strip()
                        break
                    elif line.startswith("#"):
                        desc = line.lstrip("# ").strip()
                
                skill_name = file.stem
                skills.append(Skill(name=skill_name, description=desc, content=text, file_path=file))
            except Exception:
                continue
        return skills

    def get_skill(self, name: str) -> Optional[Skill]:
        file_path = self.skills_dir / f"{name}.md"
        if not file_path.exists():
            return None
        text = file_path.read_text(encoding="utf-8")
        return Skill(name=name, description="", content=text, file_path=file_path)

    def save_skill(self, name: str, description: str, content: str) -> Path:
        # Sanitize skill name
        clean_name = re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-").lower()
        file_path = self.skills_dir / f"{clean_name}.md"
        
        full_text = f"# Skill: {clean_name}\nDescription: {description}\n\n{content}\n"
        file_path.write_text(full_text, encoding="utf-8")
        return file_path

    def get_skills_summary(self) -> str:
        skills = self.load_all_skills()
        if not skills:
            return "No custom skills installed in .skills/ directory."
        
        lines = ["Available Learned Skills:"]
        for s in skills:
            lines.append(f"- **{s.name}**: {s.description}")
        return "\n".join(lines)
