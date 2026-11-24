from typing import Dict, Any
from .base import Tool
from ..skills import SkillManager

def get_skill_tools(skill_manager: SkillManager):
    def list_skills() -> str:
        """List all available skills learned or loaded in the agent."""
        return skill_manager.get_skills_summary()

    def read_skill(skill_name: str) -> str:
        """Read the full instruction set of a specific skill."""
        skill = skill_manager.get_skill(skill_name)
        if not skill:
            return f"Error: Skill '{skill_name}' not found."
        return skill.content

    def create_skill(name: str, description: str, instructions: str) -> str:
        """Create and save a new skill for future reuse (self-improving loop)."""
        try:
            path = skill_manager.save_skill(name=name, description=description, content=instructions)
            return f"Successfully created skill '{name}' saved to '{path.name}'."
        except Exception as e:
            return f"Error creating skill: {str(e)}"

    return [
        Tool(
            name="list_skills",
            description="List all available skills from the .skills directory.",
            parameters={"type": "object", "properties": {}},
            handler=list_skills
        ),
        Tool(
            name="read_skill",
            description="Read the complete guide and steps for a specific learned skill.",
            parameters={
                "type": "object",
                "properties": {
                    "skill_name": {"type": "string", "description": "The name identifier of the skill"}
                },
                "required": ["skill_name"]
            },
            handler=read_skill
        ),
        Tool(
            name="create_skill",
            description="Save a new skill, reusable workflow, or procedure to .skills for self-improving capability.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Short identifier (e.g. 'git-release-workflow', 'debug-fastapi')"},
                    "description": {"type": "string", "description": "One sentence summary of when and how to use this skill"},
                    "instructions": {"type": "string", "description": "Detailed step-by-step instructions for performing this skill"}
                },
                "required": ["name", "description", "instructions"]
            },
            handler=create_skill
        )
    ]
