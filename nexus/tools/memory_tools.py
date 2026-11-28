import json
from typing import Any, Dict, List
from .base import Tool
from ..memory import SQLiteMemory


def get_memory_tools(memory: SQLiteMemory):
    def store_memory(
        key: str,
        content: str,
        category: str = "general",
        source: str = "agent_direct",
        confidence: float = 0.6,
        evidence: str = "",
    ) -> str:
        """Persist an explicitly requested or user-approved memory."""
        memory.store_memory(
            key=key,
            content=content,
            category=category,
            source=source,
            confidence=confidence,
            evidence=evidence,
        )
        return f"Saved active memory '{key}' ({category}); provenance and revision history recorded."

    def propose_memory(
        key: str,
        content: str,
        category: str = "preference",
        source: str = "agent_inference",
        confidence: float = 0.65,
        evidence: str = "",
    ) -> str:
        """Propose a candidate fact without exposing it to normal memory recall."""
        proposal_id = memory.propose_memory(
            key=key,
            content=content,
            category=category,
            source=source,
            confidence=confidence,
            evidence=evidence,
        )
        return f"Created memory proposal #{proposal_id}. It is pending review and is not active memory."

    def record_learning(
        key: str,
        lesson: str,
        evidence: str,
        confidence: float = 0.8,
    ) -> str:
        """Record a reusable lesson or correction as a reviewable learning proposal."""
        proposal_id = memory.propose_memory(
            key=key,
            content=lesson,
            category="learning",
            source="agent_learning",
            confidence=confidence,
            evidence=evidence,
        )
        return f"Recorded learning proposal #{proposal_id}. It will not affect future behavior until approved."

    def recall_memory(query: str, limit: int = 5) -> str:
        """Search active, approved long-term memories by keyword."""
        results = memory.recall_memories(query=query, limit=limit)
        if not results:
            return f"No active memories found matching query '{query}'."
        lines = [f"Found {len(results)} active memory record(s):"]
        for item in results:
            lines.append(
                f"- [#{item.get('id')} · {item.get('category', 'general')} · "
                f"{item.get('source', 'legacy')} · confidence {item.get('confidence', 0.5)}] "
                f"{item.get('key')}: {item.get('content')}"
            )
        return "\n".join(lines)

    def list_all_memories(limit: int = 15) -> str:
        """List active long-term memories with provenance."""
        results = memory.get_all_memories(limit=limit)
        if not results:
            return "Active memory is currently empty."
        lines = [f"Active memories ({len(results)}):"]
        for item in results:
            lines.append(
                f"- [#{item.get('id')} · {item.get('category', 'general')} · "
                f"{item.get('source', 'legacy')} · confidence {item.get('confidence', 0.5)}] "
                f"{item.get('key')}: {item.get('content')}"
            )
        return "\n".join(lines)

    def list_memory_proposals(status: str = "pending", limit: int = 20) -> str:
        """List pending, approved, or rejected memory proposals."""
        proposals = memory.list_memory_proposals(status=status, limit=limit)
        if not proposals:
            return f"No {status} memory proposals."
        lines = [f"{status.title()} memory proposals ({len(proposals)}):"]
        for item in proposals:
            lines.append(
                f"- [proposal #{item['id']} · {item['category']} · {item['source']} · "
                f"confidence {item['confidence']}] {item['key']}: {item['content']}"
                + (f"\n  Evidence: {item['evidence']}" if item.get("evidence") else "")
            )
        return "\n".join(lines)

    def review_memory_proposal(
        proposal_id: int,
        decision: str,
        reason: str = "",
    ) -> str:
        """Approve or reject a pending proposal; approval is the only path into active memory."""
        changed = memory.review_memory_proposal(
            proposal_id=proposal_id,
            decision=decision,
            reviewer="agent_or_user",
            reason=reason,
        )
        if not changed:
            return f"Proposal #{proposal_id} was not found or has already been reviewed."
        result = "approved" if decision.lower() == "approve" else "rejected"
        return f"Proposal #{proposal_id} {result}."

    def archive_memory(memory_id: int, reason: str = "") -> str:
        """Hide a memory from recall without permanently deleting its contents."""
        if not memory.archive_memory(memory_id, reason=reason, changed_by="agent_or_user"):
            return f"Active memory #{memory_id} was not found."
        return f"Archived memory #{memory_id}; it is excluded from recall and can be restored."

    def restore_memory(memory_id: int, reason: str = "") -> str:
        """Restore a previously archived memory to active recall."""
        if not memory.restore_memory(memory_id, reason=reason, changed_by="agent_or_user"):
            return f"Archived memory #{memory_id} was not found."
        return f"Restored memory #{memory_id} to active recall."

    def delete_memory(memory_id: int, reason: str = "") -> str:
        """Permanently delete a memory record and its stored history."""
        if not memory.delete_memory(memory_id, reason=reason, changed_by="agent_or_user"):
            return f"Memory #{memory_id} was not found."
        return f"Permanently deleted memory #{memory_id}."

    def memory_history(memory_id: int, limit: int = 20) -> str:
        """Show prior versions and lifecycle events for a memory record."""
        rows = memory.get_memory_history(memory_id, limit=limit)
        if not rows:
            return f"No retained revision history for memory #{memory_id}."
        lines = [f"Revision history for memory #{memory_id}:"]
        for row in rows:
            snapshot = row.get("snapshot") or {}
            lines.append(
                f"- [{row.get('created_at')}] {row.get('action')} by {row.get('changed_by')}: "
                f"{snapshot.get('key', '(memory removed)')} = {snapshot.get('content', '(no content)')}"
                + (f" · reason: {row['reason']}" if row.get("reason") else "")
            )
        return "\n".join(lines)

    def session_search(query: str, limit: int = 8) -> str:
        """Search past conversations across all stored sessions using FTS5."""
        if not hasattr(memory, "search_sessions"):
            return "Cross-session search is not available."
        hits = memory.search_sessions(query=query, limit=limit)
        if not hits:
            return f"No past conversation messages found matching '{query}'."
        lines = [f"Found {len(hits)} past session match(es) for '{query}':"]
        for hit in hits:
            session_id = hit.get("session_id", "?")
            title = hit.get("session_title") or session_id
            role = hit.get("role", "user")
            timestamp = str(hit.get("created_at", ""))[:16]
            snippet = str(hit.get("content", "")).replace("\n", " ")[:220]
            lines.append(f"- [{title} · #{session_id} · {timestamp}] ({role}): {snippet}")
        return "\n".join(lines)

    def tool(name: str, description: str, properties: Dict[str, Any], required: List[str], handler):
        return Tool(
            name=name,
            description=description,
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
            handler=handler,
        )

    return [
        tool(
            "store_memory",
            "Persist a memory only when the user explicitly asks Nexus to remember it or approves a proposal. Existing values are versioned before replacement.",
            {
                "key": {"type": "string", "description": "Stable identifier for this fact"},
                "content": {"type": "string", "description": "Fact or preference to remember"},
                "category": {"type": "string", "default": "general"},
                "source": {"type": "string", "default": "agent_direct"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.6},
                "evidence": {"type": "string", "description": "Short source or user statement supporting this fact"},
            },
            ["key", "content"],
            store_memory,
        ),
        tool(
            "propose_memory",
            "Propose a durable fact or preference inferred from conversation. Proposals remain inactive until explicitly approved.",
            {
                "key": {"type": "string"},
                "content": {"type": "string"},
                "category": {"type": "string", "default": "preference"},
                "source": {"type": "string", "default": "agent_inference"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.65},
                "evidence": {"type": "string"},
            },
            ["key", "content"],
            propose_memory,
        ),
        tool(
            "record_learning",
            "Record a reusable lesson from a user correction, failed attempt, or verified task outcome. This creates a pending proposal, not an active memory.",
            {
                "key": {"type": "string"},
                "lesson": {"type": "string"},
                "evidence": {"type": "string", "description": "Correction, failure, or verification that supports the lesson"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.8},
            },
            ["key", "lesson", "evidence"],
            record_learning,
        ),
        tool(
            "recall_memory",
            "Search active approved long-term memories; archived and pending proposals are excluded.",
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 5},
            },
            ["query"],
            recall_memory,
        ),
        tool(
            "list_all_memories",
            "List active approved long-term memory records with their provenance.",
            {"limit": {"type": "integer", "default": 15}},
            [],
            list_all_memories,
        ),
        tool(
            "list_memory_proposals",
            "List reviewable memory proposals by status: pending, approved, or rejected.",
            {
                "status": {"type": "string", "enum": ["pending", "approved", "rejected"], "default": "pending"},
                "limit": {"type": "integer", "default": 20},
            },
            [],
            list_memory_proposals,
        ),
        tool(
            "review_memory_proposal",
            "Approve or reject a pending memory proposal. Only approval makes it available to recall.",
            {
                "proposal_id": {"type": "integer"},
                "decision": {"type": "string", "enum": ["approve", "reject"]},
                "reason": {"type": "string"},
            },
            ["proposal_id", "decision"],
            review_memory_proposal,
        ),
        tool(
            "archive_memory",
            "Archive a memory so it is excluded from recall while retaining its revision history.",
            {"memory_id": {"type": "integer"}, "reason": {"type": "string"}},
            ["memory_id"],
            archive_memory,
        ),
        tool(
            "restore_memory",
            "Restore an archived memory to active recall.",
            {"memory_id": {"type": "integer"}, "reason": {"type": "string"}},
            ["memory_id"],
            restore_memory,
        ),
        tool(
            "delete_memory",
            "Permanently delete a memory record and its revision history.",
            {"memory_id": {"type": "integer"}, "reason": {"type": "string"}},
            ["memory_id"],
            delete_memory,
        ),
        tool(
            "memory_history",
            "Inspect prior values and lifecycle changes for a memory ID.",
            {"memory_id": {"type": "integer"}, "limit": {"type": "integer", "default": 20}},
            ["memory_id"],
            memory_history,
        ),
        tool(
            "session_search",
            "Search across past conversation sessions by keyword to recall earlier discussions, decisions, or solutions.",
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
            },
            ["query"],
            session_search,
        ),
    ]
