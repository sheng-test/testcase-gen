"""Step 12.3 验收测试 - V2 文件上传（multipart）。

覆盖：文件落临时目录并传入 Runtime paths、自动清理、格式/数量限制、
material_ids 组合、JSON 路径零回归、异常时仍清理。
全离线：Runtime 用 fake 捕获入参，不调用 LLM。
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from core import db as v1_db
from core.schemas import SourceType
from core.v2.runtime import PipelineResult
from web import v2_service

FAKE_RUN_ID = "01ARZ3NDEKTSV4RRFFQ69G5U01"


@pytest.fixture
def v2_db_path(tmp_path):
    from core.v2 import db as v2db
    from core.v2 import ddl

    old = v2db.get_v2_db_path()
    path = str(tmp_path / "uploads_v2.db")
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
        captured["path_contents"] = [Path(p).read_bytes() for p in kwargs.get("paths") or []]
        return PipelineResult(run_id=FAKE_RUN_ID, success=True, test_point_count=1, test_case_count=1)

    monkeypatch.setattr(v2_service, "run_v2_pipeline", fake)


def _post_multipart(client, data: dict, files):
    payload = dict(data)
    payload["files"] = files
    return client.post(
        "/api/v2/runs",
        data=payload,
        content_type="multipart/form-data",
        headers={"X-CSRF-Token": _csrf(client)},
    )


def test_markdown_upload_goes_to_runtime_paths(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(v2_client, {"title": "T", "text": ""}, [(BytesIO("退款需求".encode()), "req.md")])

    assert rv.status_code == 200, rv.get_json()
    paths = captured["paths"]
    assert len(paths) == 1
    path = Path(paths[0])
    assert path.suffix == ".md"
    assert captured["path_contents"] == ["退款需求".encode()]
    assert captured["text"] == ""
    assert captured["source_type"] == SourceType.MARKDOWN
    assert not path.exists()  # 请求结束后临时文件已清理


def test_text_plus_file_keeps_text_and_source_type(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(
        v2_client,
        {"title": "T", "text": "手写需求"},
        [(BytesIO("文件需求".encode()), "req.txt")],
    )

    assert rv.status_code == 200
    assert captured["text"] == "手写需求"
    assert captured["source_type"] == SourceType.TEXT
    assert captured["path_contents"] == ["文件需求".encode()]


def test_image_only_derives_image_source_type(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(v2_client, {"title": "T", "text": ""}, [(BytesIO(b"\x89PNG\r\n"), "screen.png")])

    assert rv.status_code == 200
    assert captured["source_type"] == SourceType.IMAGE
    assert Path(captured["paths"][0]).suffix == ".png"


def test_excel_only_derives_excel_source_type(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(v2_client, {"title": "T", "text": ""}, [(BytesIO(b"fake-xlsx"), "req.xlsx")])

    assert rv.status_code == 200
    assert captured["source_type"] == SourceType.EXCEL


def test_mixed_files_fall_back_to_text_source_type(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(
        v2_client,
        {"title": "T", "text": ""},
        [(BytesIO(b"a"), "a.md"), (BytesIO(b"b"), "b.txt")],
    )

    assert rv.status_code == 200
    assert captured["source_type"] == SourceType.TEXT


def test_upload_requires_text_or_files(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(v2_client, {"title": "T", "text": ""}, [])

    assert rv.status_code == 400
    assert "text 或 files" in rv.get_json()["error"]
    assert captured == {}


def test_upload_rejects_unsupported_extension(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(v2_client, {"title": "T", "text": ""}, [(BytesIO(b"%PDF"), "req.pdf")])

    assert rv.status_code == 400
    assert "不支持的文件类型" in rv.get_json()["error"]
    assert captured == {}


def test_upload_rejects_too_many_files(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)
    files = [(BytesIO(b"x"), f"f{i}.md") for i in range(v2_service.MAX_UPLOAD_FILES + 1)]

    rv = _post_multipart(v2_client, {"title": "T", "text": ""}, files)

    assert rv.status_code == 400
    assert "最多上传" in rv.get_json()["error"]
    assert captured == {}


def test_upload_with_material_ids(v2_client, monkeypatch):
    uid = v2_client.get("/api/me").get_json()["user"]["id"]
    mid = v1_db.create_material(uid, "退款规则", "退款金额不得超过订单金额")
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(
        v2_client,
        {"title": "T", "text": "", "material_ids": str(mid)},
        [(BytesIO("退款需求".encode()), "req.md")],
    )

    assert rv.status_code == 200
    text = captured["text"]
    assert "项目参考资料" in text
    assert "退款金额不得超过订单金额" in text
    assert Path(captured["paths"][0]).exists() is False


def test_multipart_material_ids_validation(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(
        v2_client,
        {"title": "T", "text": "需求", "material_ids": "not-an-int"},
        [],
    )

    assert rv.status_code == 400
    assert "material_ids" in rv.get_json()["error"]
    assert captured == {}


def test_json_path_unchanged(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = v2_client.post(
        "/api/v2/runs",
        json={"title": "T", "text": "原始需求"},
        headers={"X-CSRF-Token": _csrf(v2_client)},
    )

    assert rv.status_code == 200
    assert captured["text"] == "原始需求"
    assert captured["paths"] is None


def test_temp_files_cleaned_when_runtime_raises(v2_client, monkeypatch):
    captured: dict = {}

    def fake(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("boom")

    monkeypatch.setattr(v2_service, "run_v2_pipeline", fake)

    rv = _post_multipart(v2_client, {"title": "T", "text": ""}, [(BytesIO(b"x"), "req.md")])

    assert rv.status_code == 500
    assert captured["paths"]
    assert not Path(captured["paths"][0]).exists()


def test_upload_filename_cannot_escape_temp_dir(v2_client, monkeypatch):
    captured: dict = {}
    _mock_pipeline(monkeypatch, captured)

    rv = _post_multipart(v2_client, {"title": "T", "text": ""}, [(BytesIO(b"x"), "../../evil.md")])

    assert rv.status_code == 200
    path = Path(captured["paths"][0])
    assert path.name == "0.md"
    assert ".." not in path.parts
    assert path.parent.name.startswith("v2_upload_")
