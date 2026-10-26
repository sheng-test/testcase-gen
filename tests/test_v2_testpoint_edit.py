"""阶段 B 验收测试 - 测试点编辑 + 分阶段继续生成用例。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.schemas import (
    GenerationConfig,
    GenerationMode,
    GenerationScope,
    Priority,
    Provenance,
    RequirementDoc,
    RequirementVersion,
    Run,
    RunStatus,
    SourceType,
    TestCase,
    TestCaseStatus,
    TestCaseType,
    TestDimension,
    TestPoint,
    TestStep,
    new_ulid,
)
from core.v2 import repository as repo
from core.v2.runtime import PipelineResult
from web import v2_service


@pytest.fixture
def v2_db_path(tmp_path):
    from core.v2 import db as v2db
    from core.v2 import ddl

    old = v2db.get_v2_db_path()
    path = str(tmp_path / "stageb_v2.db")
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


def _csrf(client) -> str:
    return client.get("/api/me").get_json()["csrf_token"]


def _session_v2_uid(client) -> str:
    legacy_uid = client.get("/api/me").get_json()["user"]["id"]
    row = repo.get_user_by_legacy_id(legacy_uid)
    if row is not None:
        return row["id"]
    uid = new_ulid()
    repo.save_user(uid, "stageb_user", "", legacy_int_id=legacy_uid)
    return uid


def _seed_run_with_point(client, *, with_case: bool = False):
    uid = _session_v2_uid(client)
    doc = RequirementDoc(user_id=uid, title="退款需求", source_type=SourceType.TEXT)
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
    point = TestPoint(
        id=new_ulid(),
        run_id=run.id,
        version_id=version.id,
        item_ids=[],
        module="退款",
        subcategory="金额校验",
        title="退款金额不能超过订单金额",
        description="退款金额大于订单金额时拒绝",
        dimension=TestDimension.FUNCTIONAL,
        priority=Priority.P1,
        provenance=Provenance.LLM,
        generation_scope=GenerationScope.ITEM,
        fingerprint="tp_stageb_1",
    )
    repo.save_test_point(point)
    if with_case:
        repo.save_test_case(
            TestCase(
                id=new_ulid(),
                run_id=run.id,
                display_id="TC_001",
                module="退款",
                title="退款金额校验",
                expected="拒绝",
                steps=[TestStep(seq=1, action="提交")],
                priority=Priority.P1,
                type=TestCaseType.FUNCTIONAL,
                provenance=Provenance.LLM,
                status=TestCaseStatus.REVIEWED,
                generation_mode=GenerationMode.LLM,
                test_point_ids=[point.id],
                fingerprint="tc_stageb_1",
                content_hash="ch_stageb_1",
            )
        )
    return run, point


def _post(client, url, payload):
    return client.post(url, json=payload, headers={"X-CSRF-Token": _csrf(client)})


def test_edit_test_point_fields_and_preserves_identity(v2_client):
    run, point = _seed_run_with_point(v2_client)
    old_fp = point.fingerprint

    rv = _post(
        v2_client,
        f"/api/v2/test-points/{point.id}/edit",
        {
            "updates": {
                "title": "退款金额校验（人工修订）",
                "description": "退款金额大于订单金额时拒绝并提示",
                "module": "售后",
                "subcategory": "金额",
                "priority": "P0",
            }
        },
    )

    assert rv.status_code == 200, rv.get_json()
    saved = repo.get_test_point(point.id)
    assert saved is not None
    assert saved.title == "退款金额校验（人工修订）"
    assert saved.description == "退款金额大于订单金额时拒绝并提示"
    assert saved.module == "售后" and saved.subcategory == "金额"
    assert saved.priority == Priority.P0
    assert saved.provenance == Provenance.HUMAN
    assert saved.id == point.id and saved.fingerprint == old_fp
    assert saved.run_id == run.id


def test_edit_test_point_rejects_unknown_or_empty_fields(v2_client):
    _, point = _seed_run_with_point(v2_client)

    rv = _post(v2_client, f"/api/v2/test-points/{point.id}/edit", {"updates": {"item_ids": []}})
    assert rv.status_code == 400
    assert "不支持修改字段" in rv.get_json()["error"]

    rv = _post(v2_client, f"/api/v2/test-points/{point.id}/edit", {"updates": {"title": ""}})
    assert rv.status_code == 400
    assert "title" in rv.get_json()["error"]


def test_edit_test_point_locked_after_cases_exist(v2_client):
    _, point = _seed_run_with_point(v2_client, with_case=True)

    rv = _post(v2_client, f"/api/v2/test-points/{point.id}/edit", {"updates": {"title": "x"}})

    assert rv.status_code == 409
    assert "已生成测试用例" in rv.get_json()["error"]


def test_edit_test_point_owner_isolation(v2_client):
    other_uid = new_ulid()
    repo.save_user(other_uid, "other_stageb", "", legacy_int_id=987654323)
    doc = RequirementDoc(user_id=other_uid, title="别人的需求", source_type=SourceType.TEXT)
    repo.save_doc(doc)
    version = RequirementVersion(doc_id=doc.id, version_no=1, raw_text="x", provenance=Provenance.LLM)
    repo.save_version(version)
    cfg = GenerationConfig(
        model_provider="t", model_name="m", temperature=0.3, prompt_version="p", generator_version="g"
    )
    repo.save_generation_config(cfg)
    run = Run(
        user_id=other_uid,
        doc_id=doc.id,
        requirement_version_id=version.id,
        generation_config_id=cfg.id,
        status=RunStatus.DONE,
    )
    repo.save_run(run)
    point = TestPoint(
        id=new_ulid(),
        run_id=run.id,
        version_id=version.id,
        item_ids=[],
        module="m",
        subcategory="s",
        title="别人的测试点",
        description="d",
        dimension=TestDimension.FUNCTIONAL,
        provenance=Provenance.LLM,
        generation_scope=GenerationScope.ITEM,
        fingerprint="tp_other_stageb",
    )
    repo.save_test_point(point)

    rv = _post(v2_client, f"/api/v2/test-points/{point.id}/edit", {"updates": {"title": "hack"}})

    assert rv.status_code == 404
    assert repo.get_test_point(point.id).title == "别人的测试点"


def test_edit_test_point_requires_login_and_csrf(v2_anon):
    assert v2_anon.post(f"/api/v2/test-points/{new_ulid()}/edit", json={"updates": {}}).status_code == 401


def test_create_run_accepts_stop_after_strategy(v2_client, monkeypatch):
    captured: dict = {}

    def fake(**kwargs):
        captured.update(kwargs)
        return PipelineResult(run_id=new_ulid(), success=True)

    monkeypatch.setattr(v2_service, "run_v2_pipeline", fake)
    rv = _post(
        v2_client,
        "/api/v2/runs",
        {"title": "T", "text": "需求", "stop_after": "strategy"},
    )
    assert rv.status_code == 200
    assert captured["stop_after"] == "strategy"


def test_create_run_rejects_unknown_stop_after(v2_client):
    rv = _post(v2_client, "/api/v2/runs", {"title": "T", "text": "需求", "stop_after": "review"})
    assert rv.status_code == 400
    assert "stop_after" in rv.get_json()["error"]


def test_generate_cases_continues_run(v2_client, monkeypatch):
    run, _ = _seed_run_with_point(v2_client)
    captured: dict = {}

    def fake_continue(**kwargs):
        captured.update(kwargs)
        return PipelineResult(run_id=run.id, success=True, test_case_count=1)

    monkeypatch.setattr(v2_service, "continue_v2_pipeline", fake_continue)
    rv = _post(v2_client, f"/api/v2/runs/{run.id}/generate-test-cases", {})

    assert rv.status_code == 200
    assert rv.get_json()["success"] is True
    assert captured["run_id"] == run.id


def test_generate_cases_conflict_when_cases_exist(v2_client, monkeypatch):
    run, _ = _seed_run_with_point(v2_client, with_case=True)

    def fail_if_called(**kwargs):
        raise AssertionError("should not call continue pipeline")

    monkeypatch.setattr(v2_service, "continue_v2_pipeline", fail_if_called)
    rv = _post(v2_client, f"/api/v2/runs/{run.id}/generate-test-cases", {})

    assert rv.status_code == 409
    assert "已生成测试用例" in rv.get_json()["error"]


def test_generate_cases_requires_login(v2_anon):
    assert v2_anon.post(f"/api/v2/runs/{new_ulid()}/generate-test-cases").status_code == 401


def test_continue_pipeline_runs_stages(v2_client, monkeypatch):
    from core.v2 import runtime

    run, _ = _seed_run_with_point(v2_client)
    calls: list[str] = []

    def fake_synthesize(client, *, run_id, version_id=None, skip_run_status_update=False):
        calls.append("testcases")
        return SimpleNamespace(llm_calls=1, cases=[], validated_count=0, failed_count=0)

    def fake_review(client, *, run_id, skip_run_status_update=False):
        calls.append("review")
        return SimpleNamespace(reviewed_count=0)

    def fake_optimize(client, *, run_id, skip_run_status_update=False):
        calls.append("optimizer")
        return SimpleNamespace(optimizer_result=None)

    monkeypatch.setattr(runtime, "synthesize_test_cases", fake_synthesize)
    monkeypatch.setattr(runtime, "review_test_cases", fake_review)
    monkeypatch.setattr(runtime, "optimize_duplicates", fake_optimize)

    result = runtime.continue_v2_pipeline(run_id=run.id, client=object())

    assert result.success is True
    assert calls == ["testcases", "review", "optimizer"]
    assert repo.get_run(run.id).status == RunStatus.DONE


def test_continue_pipeline_refuses_existing_cases(v2_client):
    from core.v2 import runtime

    run, _ = _seed_run_with_point(v2_client, with_case=True)
    result = runtime.continue_v2_pipeline(run_id=run.id, client=object())
    assert result.success is False
    assert result.failed_step == "testcases"
    assert "已存在测试用例" in result.error_message
