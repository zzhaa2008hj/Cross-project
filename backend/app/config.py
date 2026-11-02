"""运行期配置：数据目录、vault 只读来源路径、导入对账预期。

数据目录在本项目登记的 Git 外存储，容器内通过 CP_DATA_DIR 注入。
vault 只读挂载路径由 CP_VAULT_DIR 注入，正式写回不在 E1 范围内。
"""
from __future__ import annotations

import os
from pathlib import Path

COMPANY_ID = "8710e601-99d7-4604-b4e6-6781a7300541"
PROJECT_ID = "52a8eeac-d442-420e-af14-663ffd7af0ee"
RESOURCE_PREFIX = "pc-52a8eeac"

_DEFAULT_DATA_DIR = Path.home() / ".local/share/paperclip-project-data" / PROJECT_ID
_DEFAULT_VAULT_DIR = Path("/home/hui/MyData/AI/my-vault")

# 首版导入来源（只读）
MILESTONE_SOURCE_REL = "20_项目/里程碑.md"
PERSONNEL_SOURCE_REL = "99_系统/人员.md"
PROJECT_NOTES_DIR_REL = "20_项目"

# 对账预期：来自首版计划，差异必须在报告中说明
EXPECTED_MILESTONE_COUNT = 35
EXPECTED_MAINTENANCE_PROJECT_COUNT = 7

# 产品已确认但 vault 源里尚未记录的口径，只进"待确认"，不静默推断
BEIJING_WAREHOUSE_ROLES = {
    "project_owner": "李冠男",
    "executor": "郑伊平",
    "coordinator": "赵辉辉",
}

PROJECT_STATES = ("active", "on-hold", "done", "maintenance")
MILESTONE_STATES = (
    "外部阻塞",
    "内部资源阻塞",
    "进行中",
    "未开始",
    "已完成",
    "已取消",
)
TERMINAL_MILESTONE_STATES = ("已完成", "已取消")


def data_dir() -> Path:
    return Path(os.environ.get("CP_DATA_DIR", str(_DEFAULT_DATA_DIR)))


def db_path() -> Path:
    return data_dir() / "sqlite" / "crossproject.db"


def vault_dir() -> Path:
    return Path(os.environ.get("CP_VAULT_DIR", str(_DEFAULT_VAULT_DIR)))


def source_path(rel: str) -> Path:
    return vault_dir() / rel
