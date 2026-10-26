"""阶段 A1 验收测试 - V2 测试点 XMind 导出。"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

import pytest

from core.schemas import (
    GenerationConfig,
    GenerationScope,
    Priority,
    Provenance,
    RequirementDoc,
    RequirementVersion,
    Run,
    RunStatus,
    SourceType,
    TestDimension,
    TestPoint,
    new_ulid,
)
from core.v2 import repository as repo


@pytest.fixture
def v2_db_path(tmp_path):
    from core.v2 import db as v2db
    from core.v2 import ddl

    old = v2db.get_v2_db_path()
    path = str(tmp_path / "xmind_v2.db")
    v2db.set_v2_db_path(path)
    ddl.create_v2_schema()
    yield path
    v2db.set_v2_db_path(old)


@pytest.fixture
def v2_client(auth_client, v2_db_path):
    return auth_client


@pytest.fixture
def v2_anon(client, v2_db_path):
    return client


def _session_v2_uid(client) -> str:
    legacy_uid = client.get("/api/me").get_json()["user"]["id"]
    row = repo.get_user_by_legacy_id(legacy_uid)
    if row is not None:
        return row["id"]
    uid = new_ulid()
    repo.save_user(uid, "xmind_user", "", legacy_int_id=legacy_uid)
    return uid


def _create_run(uid: str, title: str = "退款需求") -> Run:
    doc = RequirementDoc(user_id=uid, title=title, source_type=SourceType.TEXT)
    repo.save_doc(doc)
    version = RequirementVersion(doc_id=doc.id, version_no=1, raw_text="退款需求", provenance=Provenance.LLM)
    repo.save_version(version)
    cfg = GenerationConfig(
        model_provider="test", model_name="fake", temperature=0.3, prompt_version="p", generator_version="g"
    )
    repo.save_generation_config(cfg)
    run = Run(
        user_id=uid,
        doc_id=doc.id,
        requirement_version_id=version.id,
        generation_config_id=cfg.id,
        status=RunStatus.DONE,
    )
    repo.save_run(run)
    return run


def _seed(client) -> Run:
    uid = _session_v2_uid(client)
    run = _create_run(uid)
    points = [
        ("登录", "正常登录", "手机号验证码登录成功", Priority.P1),
        ("登录", "异常登录", "验证码错误提示", Priority.P0),
        ("退款", "金额校验", "退款金额超过订单金额", Priority.P1),
    ]
    for i, (module, subcategory, title, priority) in enumerate(points, 1):
        repo.save_test_point(
            TestPoint(
                id=new_ulid(),
                run_id=run.id,
                version_id=run.requirement_version_id,
                item_ids=[],
                module=module,
                subcategory=subcategory,
                title=title,
                description=f"{title}的描述",
                dimension=TestDimension.FUNCTIONAL,
                priority=priority,
                provenance=Provenance.LLM,
                generation_scope=GenerationScope.ITEM,
                fingerprint=f"tp_xmind_{i}",
            )
        )
    return run


def _titles(node: dict) -> list[str]:
    result = [node.get("title", "")]
    for child in (node.get("children") or {}).get("attached", []):
        result.extend(_titles(child))
    return result


def test_export_test_points_xmind_structure(v2_client):
    run = _seed(v2_client)

    rv = v2_client.get(f"/api/v2/runs/{run.id}/test-points/export")

    assert rv.status_code == 200
    assert rv.mimetype == "application/x-xmind"
    assert "attachment" in rv.headers["Content-Disposition"]
    assert ".xmind" in rv.headers["Content-Disposition"]
    with zipfile.ZipFile(BytesIO(rv.data)) as zf:
        content = json.loads(zf.read("content.json"))
        assert "metadata.json" in zf.namelist()
        assert "manifest.json" in zf.namelist()
    assert content[0]["title"] == "测试点"
    root = content[0]["rootTopic"]
    assert root["title"] == "退款需求"
    titles = _titles(root)
    assert "登录" in titles and "退款" in titles
    assert "正常登录" in titles and "异常登录" in titles and "金额校验" in titles
    assert "手机号验证码登录成功" in titles
    assert any("优先级：P0" in title for title in titles)


def test_export_test_points_owner_isolation(v2_client):
    _seed(v2_client)
    other_uid = new_ulid()
    repo.save_user(other_uid, "other_xmind", "", legacy_int_id=987654322)
    other_run = _create_run(other_uid, "别人的需求")

    rv = v2_client.get(f"/api/v2/runs/{other_run.id}/test-points/export")

    assert rv.status_code == 404


def test_export_test_points_requires_login(v2_anon):
    assert v2_anon.get(f"/api/v2/runs/{new_ulid()}/test-points/export").status_code == 401


def test_export_test_points_missing_run(v2_client):
    assert v2_client.get(f"/api/v2/runs/{new_ulid()}/test-points/export").status_code == 404


def test_export_test_points_gating_503(v2_client, monkeypatch):
    import web

    run = _seed(v2_client)
    monkeypatch.setitem(web.app.config, "V2_READY", False)
    assert v2_client.get(f"/api/v2/runs/{run.id}/test-points/export").status_code == 503


def test_export_test_points_empty_run(v2_client):
    uid = _session_v2_uid(v2_client)
    run = _create_run(uid, "空需求")

    rv = v2_client.get(f"/api/v2/runs/{run.id}/test-points/export")

    assert rv.status_code == 200
    with zipfile.ZipFile(BytesIO(rv.data)) as zf:
        content = json.loads(zf.read("content.json"))
    assert content[0]["rootTopic"]["title"] == "空需求"
    assert (content[0]["rootTopic"].get("children") or {}).get("attached") == []
