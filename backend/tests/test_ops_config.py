"""E4 Task 7：部署配置检查（compose 备份挂载、固定镜像、README 使用说明）。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
DOCKERFILE = ROOT / "backend" / "Dockerfile"
README = ROOT / "README.md"

DATA_ROOT = "/home/hui/.local/share/paperclip-project-data/52a8eeac-d442-420e-af14-663ffd7af0ee"


def _compose_text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


def _bind_mount_source(text: str, target: str) -> str | None:
    """从 compose 里找出指向 ``target`` 的 bind mount 源路径。"""
    block: list[str] = []
    for line in text.splitlines() + [""]:
        stripped = line.strip()
        if stripped == "- type: bind":
            block = []
            continue
        # 缩进小于 6 空格说明离开了当前挂载块
        if line and not line.startswith("      "):
            block = []
            continue
        if not stripped:
            continue
        block.append(stripped)
        src = next((b for b in block if b.startswith("source: ")), None)
        tgt = next((b for b in block if b.startswith("target: ")), None)
        if src and tgt and tgt.split(": ", 1)[1] == target:
            return src.split(": ", 1)[1]
    return None


def test_compose_declares_backup_dir_env():
    assert "CP_BACKUP_DIR" in _compose_text()


def test_compose_mounts_backups_from_project_data_dir():
    source = _bind_mount_source(_compose_text(), "/backups")

    assert source is not None, "compose 缺少 /backups 绑定挂载"
    assert source == f"{DATA_ROOT}/backups"
    # 备份必须落在本项目数据目录，不能写进 vault
    assert "vault" not in source.lower()


def test_compose_uses_fixed_image_tags():
    text = _compose_text()

    assert "pc-52a8eeac-backend:hui211-e4" in text
    assert "pc-52a8eeac-frontend:hui211-e4" in text


def test_dockerfile_sets_backup_dir_and_healthcheck():
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "CP_BACKUP_DIR=/backups" in text
    assert "HEALTHCHECK" in text


def test_readme_documents_preview_backup_restore_and_limits():
    text = README.read_text(encoding="utf-8")

    assert "CP_BACKUP_DIR" in text
    assert "hui211-e4" in text
    assert "app.backup_cli backup" in text
    assert "app.backup_cli restore" in text
    assert "已知限制" in text
