"""部署配置检查（自用简化编排：数据落在项目目录 ./data）。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
DOCKERFILE = ROOT / "backend" / "Dockerfile"
NGINX = ROOT / "frontend" / "nginx.conf"
README = ROOT / "README.md"


def _compose_text() -> str:
    return COMPOSE.read_text(encoding="utf-8")


def _mounts(text: str) -> list[str]:
    return [
        line.strip()[2:].strip()
        for line in text.splitlines()
        if line.strip().startswith("- ") and ":" in line
    ]


def test_compose_mounts_data_from_project_dir():
    assert "./data:/data" in _mounts(_compose_text())


def test_compose_backups_stay_under_data_dir():
    text = _compose_text()

    assert "CP_BACKUP_DIR: /data/backups" in text
    # 备份不再单独挂载，全部落在 ./data 内
    assert not any(m.endswith(":/backups") for m in _mounts(text))
    # 导入导出功能已移除：不得再挂 vault，也不得再配置导出目录
    assert not any("/vault" in m for m in _mounts(text))
    assert "CP_EXPORT_DIR" not in text
    assert "CP_VAULT_DIR" not in text


def test_compose_runs_backend_as_host_user():
    assert 'user: "1000:1000"' in _compose_text()


def test_compose_binds_only_loopback_port():
    assert '"127.0.0.1:18330:80"' in _compose_text()


def test_compose_uses_fixed_image_tags():
    text = _compose_text()

    assert "pc-52a8eeac-backend:local" in text
    assert "pc-52a8eeac-frontend:local" in text


def test_dockerfile_sets_backup_dir_and_healthcheck():
    text = DOCKERFILE.read_text(encoding="utf-8")

    assert "CP_BACKUP_DIR=/data/backups" in text
    assert "HEALTHCHECK" in text


def test_nginx_proxies_to_backend_service_name():
    text = NGINX.read_text(encoding="utf-8")

    assert "http://backend:8000" in text
    assert "cp-develop-backend" not in text


def test_readme_documents_preview_backup_restore_and_limits():
    text = README.read_text(encoding="utf-8")

    assert "CP_BACKUP_DIR" in text
    assert "pc-52a8eeac-backend:local" in text
    assert "app.backup_cli backup" in text
    assert "app.backup_cli restore" in text
    assert "已知限制" in text
