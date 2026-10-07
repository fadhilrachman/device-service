from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from config import REMOTE_DATABASE_URL

load_dotenv()

# All reads/writes go straight to the shared database (same as the admin
# panel backend). There is no local SQLite anymore: offline support is handled
# client-side by the kiosk.
connect_args = (
    {"connect_timeout": 5} if REMOTE_DATABASE_URL.startswith("postgresql") else {}
)
# Neon closes idle serverless connections, and its pooler can drop a socket that
# has been open too long, which surfaces as "server closed the connection
# unexpectedly" in the middle of a request. pool_pre_ping validates a pooled
# connection before it is handed out, and pool_recycle retires connections well
# before the server would drop them, so a stale socket is never used for a query.
remote_engine = create_engine(
    REMOTE_DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
    pool_recycle=240,
)

remote_session = sessionmaker(autocommit=False, autoflush=False, bind=remote_engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = remote_session()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    import models  # noqa: F401  (registers all tables on Base.metadata)

    try:
        Base.metadata.create_all(bind=remote_engine)
    except Exception:
        # A native enum type already existing (created by Alembic) may make
        # creation fail -- that is expected and safe to ignore.
        pass
