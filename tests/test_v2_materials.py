"""Step 12.2 验收测试 - V2 项目材料引用。

覆盖：材料文本注入、无材料时行为不变、用户隔离、重复/数量/类型校验、text 仍必填。
全离线：Runtime 用 fake 捕获入参，不调用 LLM。
"""

from __future__ import annotations

import pytest

from core import db as v1_db
from core.v2.runtime import PipelineResult
from web import v2_service

FAKE_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5M01"


@pytest.fixture
def v2_db_path(tmp_path):
    from core.v2 import db as v2db
    from core.v2 import ddl

    old = v2db.get_v2_db_path()
    path = str(tmp_path / "materials_v2.db")
    v2db.set_v2_db_path(path)
    ddl.create_v2_schema()
    yield path
    v2db.set_v2_db_path(old)


@pytest.fixture
def v2_client(auth_client, v2_db_path):
    return auth_client


def _csrf(client) -> str:
    return client.get("/api/me").get_json()["csrf_token"]


def _mock_pipeline(monkeypatch, captured: dict) -> None:
    def fake(**kwargs):
        captured.update(kwargs)
        return PipelineResult(run_id=FAKE_RUN_ID, success=True, test_point_count=1, test_case_count=1)

    monkeypatch.setattr(v2_service, "run_v2_pipeline", fake)


def _post(client, payload: dict):
    return client.post("/api/v2/runs", json=payload, headers={"X-CSRF-Token": _csrf(client)})


def _v1_uid(client) -> int:
    return client.get("/api/me").get_json()["user"]["id"]


def test_material_text_injected_into_requirement(v2_client, monkeypatch):
    uid = _v1_uid(v2_client)
    mid = v1_db.create_material(uid, "退款规则", "退款金额不得超过订单金额")
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post(v2_client, {"title": "退款需求", "text": "原始需求描述", "material_ids": [mid]})

    assert rv.status_code == 200, rv.get_json()
    text = captured["text"]
    assert text.startswith("原始需求描述")
    assert "项目参考资料（仅作背景上下文，不单独作为需求项）" in text
    assert "【退款规则】" in text
    assert "退款金额不得超过订单金额" in text


def test_without_material_ids_text_is_unchanged(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post(v2_client, {"title": "T", "text": "原始需求"})

    assert rv.status_code == 200
    assert captured["text"] == "原始需求"


def test_duplicate_material_ids_are_deduplicated(v2_client, monkeypatch):
    uid = _v1_uid(v2_client)
    mid = v1_db.create_material(uid, "退款规则", "只出现一次")
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post(v2_client, {"title": "T", "text": "需求", "material_ids": [mid, mid]})

    assert rv.status_code == 200
    assert captured["text"].count("【退款规则】") == 1


def test_other_users_material_is_not_injected(v2_client, monkeypatch):
    other_uid = v1_db.create_user("other_material_user", "password123")
    other_mid = v1_db.create_material(other_uid, "别人的资料", "不应泄露的内容")
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post(v2_client, {"title": "T", "text": "需求", "material_ids": [other_mid]})

    assert rv.status_code == 200
    assert captured["text"] == "需求"
    assert "不应泄露的内容" not in captured["text"]


@pytest.mark.parametrize(
    ("material_ids", "message"),
    [
        ("1", "整数数组"),
        ([True], "整数数组"),
        ([1, "2"], "整数数组"),
        ([0], "正整数"),
        ([-1], "正整数"),
        ([1, 2, 3, 4, 5, 6], "最多选择 5 个"),
    ],
)
def test_material_ids_validation(v2_client, monkeypatch, material_ids, message):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post(v2_client, {"title": "T", "text": "需求", "material_ids": material_ids})

    assert rv.status_code == 400
    assert message in rv.get_json()["error"]
    assert captured == {}


def test_text_required_even_with_materials(v2_client, monkeypatch):
    uid = _v1_uid(v2_client)
    mid = v1_db.create_material(uid, "资料", "内容")
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post(v2_client, {"title": "T", "text": "", "material_ids": [mid]})

    assert rv.status_code == 400
    assert captured == {}


def test_material_ids_null_is_treated_as_none(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post(v2_client, {"title": "T", "text": "需求", "material_ids": None})

    assert rv.status_code == 200
    assert captured["text"] == "需求"
