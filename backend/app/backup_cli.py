"""E4：备份/恢复命令行入口。

用法::

    python -m app.backup_cli backup [--db PATH] [--backup-dir PATH] [--stamp S]
    python -m app.backup_cli restore --source PATH [--db PATH] [--stamp S]

恢复是离线操作：会先确认应用已停（库锁），失败时退出码非 0 并打印原因。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import db_path as default_db_path
from .services.backup import backup_root, default_stamp, run_backup
from .services.restore import restore_sqlite


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="app.backup_cli", description="跨项目管理软件：备份与恢复"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    backup = sub.add_parser("backup", help="做一次一致性备份")
    backup.add_argument("--db", default=None, help="数据库路径")
    backup.add_argument("--backup-dir", default=None, help="备份根目录")
    backup.add_argument("--stamp", default=None, help="备份版本号（默认 UTC 时间戳）")

    restore = sub.add_parser("restore", help="从备份恢复")
    restore.add_argument("--source", required=True, help="恢复来源文件（SQLite 库）")
    restore.add_argument("--db", default=None, help="数据库路径")
    restore.add_argument("--stamp", default=None, help="回滚副本版本号")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "backup":
            db = Path(args.db) if args.db else default_db_path()
            root = Path(args.backup_dir) if args.backup_dir else backup_root()
            result = run_backup(db, root, args.stamp)
        else:
            db = Path(args.db) if args.db else default_db_path()
            stamp = args.stamp or default_stamp()
            result = restore_sqlite(Path(args.source), db, stamp)
    except Exception as exc:  # noqa: BLE001  CLI 边界：任何失败都要报原因
        print(f"失败：{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
