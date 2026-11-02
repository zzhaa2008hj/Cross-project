from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config


class Base(DeclarativeBase):
    pass


def _engine_url() -> str:
    override = config.db_path()
    override.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{override}"


engine = create_engine(
    _engine_url(),
    connect_args={"check_same_thread": False},
    future=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - 连接级设置
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    from . import models  # noqa: F401  确保模型注册

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


# 新增列不会由 create_all 补齐（已存在的表只会保持原样），
# 这里做一次轻量补列，保证旧预览库升级后仍可用。
_ADDED_COLUMNS = {
    "milestones": [("source_dep_names", "TEXT")],
    "persons": [("skills", "TEXT DEFAULT ''")],
}


def _add_missing_columns() -> None:
    """在已有库上补列。

    反射可能读到过期快照（同一连接上已有未结束事务），所以 ALTER 遇到
    "duplicate column" 视为已补齐，保证重复执行安全且不丢数据。
    """
    from sqlalchemy import inspect, text
    from sqlalchemy.exc import OperationalError

    with engine.connect() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        for table, columns in _ADDED_COLUMNS.items():
            if table not in tables:
                continue
            existing = {col["name"] for col in inspector.get_columns(table)}
            for name, ddl in columns:
                if name in existing:
                    continue
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    conn.commit()
                except OperationalError as exc:
                    conn.rollback()
                    if "duplicate column" not in str(exc).lower():
                        raise


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
