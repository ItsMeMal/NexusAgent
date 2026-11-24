from typing import Dict, Any
from .base import Tool
from ..memory import SQLiteMemory

def get_memory_tools(memory: SQLiteMemory):
    def store_memory(key: str, content: str, category: str = "general") -> str:
        """Store persistent knowledge, preference, or fact into memory."""
        success = memory.store_memory(key=key, content=content, category=category)
        if success:
            return f"Successfully saved memory '{key}' under category '{category}'."
        return f"Failed to store memory '{key}'."

    def recall_memory(query: str, limit: int = 5) -> str:
        """Search memory for relevant facts, notes, and past user preferences."""
        results = memory.recall_memories(query=query, limit=limit)
        if not results:
            return f"No memories found matching query '{query}'."
        
        output = [f"Found {len(results)} memory record(s):"]
        for r in results:
            output.append(f"- [{r.get('category', 'general')}] {r.get('key')}: {r.get('content')}")
        return "\n".join(output)

    def list_all_memories(limit: int = 15) -> str:
        """List recently stored memories."""
        results = memory.get_all_memories(limit=limit)
        if not results:
            return "Memory is currently empty."
        output = [f"Recent {len(results)} memory record(s):"]
        for r in results:
            output.append(f"- [{r.get('category', 'general')}] {r.get('key')}: {r.get('content')}")
        return "\n".join(output)

    return [
        Tool(
            name="store_memory",
            description="Save a persistent fact, preference, or learning into SQLite long-term memory.",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Short identifier or label for this memory"},
                    "content": {"type": "string", "description": "The detailed information or knowledge to remember"},
                    "category": {"type": "string", "description": "Category (e.g. 'preference', 'tech_stack', 'bug_fix')", "default": "general"}
                },
                "required": ["key", "content"]
            },
            handler=store_memory
        ),
        Tool(
            name="recall_memory",
            description="Search SQLite persistent memory for relevant knowledge or past facts using keyword search.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search keyword or phrase to look up"},
                    "limit": {"type": "integer", "description": "Maximum number of memories to return", "default": 5}
                },
                "required": ["query"]
            },
            handler=recall_memory
        ),
        Tool(
            name="list_all_memories",
            description="List recently saved memory items.",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Maximum records to return", "default": 15}
                }
            },
            handler=list_all_memories
        )
    ]
