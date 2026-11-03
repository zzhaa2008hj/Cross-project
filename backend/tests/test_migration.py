"""E2 迁移测试：旧 E1 库升级后保留原值且可重复执行。"""
from sqlalchemy import inspect, text

from app.db import _add_missing_columns, engine


def _create_e1_persons_table():
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS persons"))
        conn.execute(
            text(
                "CREATE TABLE persons ("
                "id INTEGER PRIMARY KEY, name TEXT, roles TEXT, weekly_capacity REAL,"
                "note TEXT, archived BOOLEAN, source_ref TEXT, source_record_hash TEXT,"
                "edited_in_app BOOLEAN, created_at DATETIME, updated_at DATETIME)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO persons (id, name, roles, weekly_capacity, archived)"
                " VALUES (9001, '老同事', '统筹管理', 4.5, 0)"
            )
        )


def test_add_person_skills_column_keeps_existing_values():
    _create_e1_persons_table()
    try:
        _add_missing_columns()
        _add_missing_columns()  # 幂等：重复执行不报错也不丢数据
        columns = {col["name"] for col in inspect(engine).get_columns("persons")}
        assert "skills" in columns
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT name, roles, weekly_capacity, skills, monthly_capacity"
                    " FROM persons WHERE id = 9001"
                )
            ).one()
        assert row.name == "老同事"
        assert row.roles == "统筹管理"
        assert row.weekly_capacity == 4.5
        assert row.skills in (None, "")
        # 存量人员的核定人天补成 30
        assert row.monthly_capacity == 30.0
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS persons"))
