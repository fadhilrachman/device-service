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
remote_engine = create_engine(REMOTE_DATABASE_URL, connect_args=connect_args)

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
