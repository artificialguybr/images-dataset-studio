from sqlmodel import Session, SQLModel, create_engine, select

from .config import get_settings

_settings = get_settings()
_settings.ensure_dirs()

_url = _settings.database_url
connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}
engine = create_engine(_url, echo=False, connect_args=connect_args)

if _url.startswith("sqlite"):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=10000")
        cur.close()


def init_db() -> None:
    # Import models so SQLModel.metadata is populated
    from . import models  # noqa: F401
    SQLModel.metadata.create_all(engine)


def get_session():
    with Session(engine) as session:
        yield session
