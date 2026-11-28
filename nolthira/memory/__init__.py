from .sqlite_memory import SQLiteMemory as _SQLiteMemory
from .governed import MemoryGovernanceMixin


class SQLiteMemory(MemoryGovernanceMixin, _SQLiteMemory):
    """SQLite memory with provenance, reviewable learning, and auditable lifecycle."""

    def __init__(self, db_path):
        _SQLiteMemory.__init__(self, db_path)
        self._init_governance()


__all__ = ["SQLiteMemory"]
