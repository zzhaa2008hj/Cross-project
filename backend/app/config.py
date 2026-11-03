"""运行期配置：数据目录。

数据目录在本项目登记的 Git 外存储，容器内通过 CP_DATA_DIR 注入。
"""
from __future__ import annotations

import os
from pathlib import Path

COMPANY_ID = "8710e601-99d7-4604-b4e6-6781a7300541"
PROJECT_ID = "52a8eeac-d442-420e-af14-663ffd7af0ee"
# Docker 资源名前缀：容器/镜像/网络统一用它，必须与 docker-compose.yml 的 name: 一致
RESOURCE_PREFIX = "cross-project"

_DEFAULT_DATA_DIR = Path.home() / ".local/share/paperclip-project-data" / PROJECT_ID

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

# E2：项目职责（只记录角色，不产生占用）
ASSIGNMENT_ROLES = ("项目负责人", "业务对接", "节点执行", "统筹管理")
# E2：分配类型——关联节点，或整体项目管理投入
ALLOCATION_KINDS = ("milestone", "project_management")


def data_dir() -> Path:
    return Path(os.environ.get("CP_DATA_DIR", str(_DEFAULT_DATA_DIR)))


def db_path() -> Path:
    return data_dir() / "sqlite" / "crossproject.db"
