from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import LOCAL_DB_PATH, REMOTE_DATABASE_URL

load_dotenv()

# Tables that are LOCAL-ONLY (tracking / outbox) and must never be created on the
# shared PostgreSQL database.
LOCAL_ONLY_TABLES = {"sync_outbox", "sync_markers"}

# Additive columns for existing SQLite databases (fresh installs get them via
# create_all). Ordered: (table, column, ddl) -- ddl must match the model type.
ADDITIVE_COLUMNS = [
    (
        "devices",
        "tenant_id",
        "VARCHAR(36)",
    ),
    (
        "sessions",
        "frame_template_id",
        "VARCHAR(36)",
    ),
    (
        "session_device_logs",
        "frame_template_id",
        "VARCHAR(36)",
    ),
    (
        "session_device_logs",
        "frame_template_name",
        "TEXT",
    ),
]

local_engine = create_engine(
    f"sqlite:///{LOCAL_DB_PATH}",
    connect_args={"check_same_thread": False},
)
remote_engine = create_engine(
    REMOTE_DATABASE_URL,
    connect_args={"connect_timeout": 5},
)

local_session = sessionmaker(autocommit=False, autoflush=False, bind=local_engine)
remote_session = sessionmaker(autocommit=False, autoflush=False, bind=remote_engine)

Base = declarative_base()


@event.listens_for(local_engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_db() -> Generator[Session, None, None]:
    db = local_session()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    import models  # noqa: F401  (registers all tables on Base.metadata)

    # Local SQLite gets every table (shared + local-only tracking tables).
    Base.metadata.create_all(bind=local_engine)
    _additive_migrate_local()
    _data_migrate_local()

    # Remote PostgreSQL is normally provisioned by the admin panel (Alembic).
    # Only create the shared tables, never our local-only tracking tables.
    remote_tables = [
        t for t in Base.metadata.sorted_tables if t.name not in LOCAL_ONLY_TABLES
    ]
    try:
        Base.metadata.create_all(bind=remote_engine, tables=remote_tables)
    except Exception:
        # A native enum type already existing (created by Alembic) may make
        # creation fail -- that is expected and safe to ignore.
        pass


def _additive_migrate_local() -> None:
    with local_engine.connect() as conn:
        for table_name, column, ddl in ADDITIVE_COLUMNS:
            has_column = conn.execute(
                text(
                    "SELECT COUNT(*) FROM pragma_table_info(:t) WHERE name = :c"
                ),
                {"t": table_name, "c": column},
            ).scalar()
            if has_column:
                continue
            conn.execute(text(f'ALTER TABLE "{table_name}" ADD COLUMN "{column}" {ddl}'))
        # SQLite ALTER TABLE does not create indexes: UNIQUE tenant_id must allow
        # multiple NULLs (satisfies optional & unique on both SQLite and Postgres).
        conn.execute(
            text(
                'CREATE UNIQUE INDEX IF NOT EXISTS "ix_devices_tenant_id"'
                ' ON "devices" ("tenant_id")'
            )
        )
        conn.commit()


def _data_migrate_local() -> None:
    """Normalize legacy session values to the new enums on existing SQLite DBs."""
    with local_engine.connect() as conn:
        conn.execute(
            text("UPDATE sessions SET activation_mode = 'qr' WHERE activation_mode = 'cash'")
        )
        conn.execute(
            text("UPDATE sessions SET state = 'started' WHERE state = 'created'")
        )
        conn.execute(
            text("UPDATE sessions SET state = 'take_photo' WHERE state = 'captured'")
        )
        conn.execute(
            text("UPDATE sessions SET state = 'complete' WHERE state IN ('rendered', 'printed', 'completed', 'success')")
        )