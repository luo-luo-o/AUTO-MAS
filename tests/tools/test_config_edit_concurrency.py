import sqlite3

import pytest

from app.core.config_edit import ConfigEditError, ConfigEditLeaseService, ConfigEditResource
from app.utils.io import file_collection_fingerprint, file_fingerprint


def test_file_fingerprint_is_stable_and_changes(tmp_path):
    config_file = tmp_path / "Config.json"

    missing = file_fingerprint(config_file)
    assert missing == file_fingerprint(config_file)

    config_file.write_text('{"a": 1}', encoding="utf-8")
    first = file_fingerprint(config_file)
    assert first == file_fingerprint(config_file)
    assert first != missing

    config_file.write_text('{"a": 2}', encoding="utf-8")
    assert file_fingerprint(config_file) != first


def test_file_collection_fingerprint_tracks_each_member(tmp_path):
    first = tmp_path / "ToolsConfig.json"
    second = tmp_path / "GameSignAccounts.json"
    first.write_text("tools", encoding="utf-8")

    before = file_collection_fingerprint((first, second))
    second.write_text("accounts", encoding="utf-8")
    assert file_collection_fingerprint((first, second)) != before


def test_config_edit_lease_conflict_renew_release_and_reacquire(tmp_path):
    db_path = tmp_path / "data.db"
    resource_file = tmp_path / "ScriptConfig.json"
    resource_file.write_text("{}", encoding="utf-8")
    resource = ConfigEditResource("ScriptConfig", (resource_file,))
    service = ConfigEditLeaseService(db_path)
    service.init_schema()

    lease = service.acquire(resource)
    assert lease.token

    with pytest.raises(ConfigEditError, match="有其他用户正在编辑该配置"):
        service.acquire(resource)

    renewed = service.renew(resource, lease.token)
    assert renewed.token == lease.token

    assert not service.release(resource.key, "old-token")
    assert service.release(resource.key, lease.token)

    next_lease = service.acquire(resource)
    assert next_lease.token != lease.token


def test_config_edit_lease_expires(tmp_path):
    db_path = tmp_path / "data.db"
    resource_file = tmp_path / "QueueConfig.json"
    resource_file.write_text("{}", encoding="utf-8")
    resource = ConfigEditResource("QueueConfig", (resource_file,))
    service = ConfigEditLeaseService(db_path)
    service.init_schema()

    lease = service.acquire(resource)
    with sqlite3.connect(db_path) as db:
        db.execute(
            "UPDATE config_edit_lease SET expires_at = 0 WHERE token = ?",
            (lease.token,),
        )

    next_lease = service.acquire(resource)
    assert next_lease.token != lease.token


def test_save_allowed_rejects_external_file_change(tmp_path):
    db_path = tmp_path / "data.db"
    resource_file = tmp_path / "PlanConfig.json"
    resource_file.write_text('{"plans": []}', encoding="utf-8")
    resource = ConfigEditResource("PlanConfig", (resource_file,))
    service = ConfigEditLeaseService(db_path)
    service.init_schema()

    lease = service.acquire(resource)
    service.assert_save_allowed(
        resource,
        token=lease.token,
        base_version=lease.version,
    )

    resource_file.write_text('{"plans": ["external"]}', encoding="utf-8")
    with pytest.raises(ConfigEditError, match="配置已被外部修改"):
        service.assert_save_allowed(
            resource,
            token=lease.token,
            base_version=lease.version,
        )
