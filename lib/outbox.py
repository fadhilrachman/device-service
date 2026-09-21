from models.sync import SyncOutbox


def enqueue(db, table_name: str, row_id: str, op: str = "upsert") -> SyncOutbox:
    """Add a row to the local to-be-synced queue."""
    entry = SyncOutbox(table_name=table_name, row_id=row_id, op=op)
    db.add(entry)
    return entry