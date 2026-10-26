"""V2 REST API blueprint（Step 10.3）。

★ P0-2：本层只负责 HTTP（参数校验 → 调 v2_service → 统一响应）；绝不控制 Run 状态、不实现业务流程。
        业务流程全下沉到 core/v2/runtime.py（Runtime 是 Run 状态唯一控制者）。
★ P0-4：POST /runs 同步执行 = MVP 已知限制；10.3 不实现 Celery / Redis / 消息队列 / 后台 Job，异步化留未来。
★ P0-5：只接已有 core/v2 能力，不扩 Runtime、不新增 AI 能力；POST /runs 支持 JSON 与 multipart（Step 12.3 文件输入）。
★ 端点（Step 10.3.1 + Step 11 UI 重构 + Step 12.1 导出）：共 15 个 /api/v2/* 端点 = health + POST /runs + GET /runs（列表）
        + GET /runs/<id>{,/test-points,/test-cases,/review,/optimizer,/coverage,/requirements,/export}
        + POST /test-cases/<id>{/edit,/re-review} + GET /test-cases/<id>{/revisions,/trace}。
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file, session

from core.v2 import repository as repo
from web import v2_service
from web.utils import csrf_protect, login_required

logger = logging.getLogger("web")

bp = Blueprint("v2", __name__)


@bp.before_request
def _gate_v2_ready():
    """V2_READY 闸门（消费 10.1 留下的 app.config["V2_READY"]）。

    /api/v2/health 免 gating（P0-1，探活端点必须始终可达）；其余端点未 ready → 统一 503。
    """
    if request.path == "/api/v2/health":
        return None
    if not current_app.config.get("V2_READY", False):
        return jsonify({"error": "V2 未就绪（初始化失败），暂不可用", "status": "degraded", "v2_ready": False}), 503
    return None


# ============================================================
# 健康检查（P0-1：免登录、免 gating）
# ============================================================


@bp.route("/api/v2/health", methods=["GET"])
def v2_health():
    """V2 独立健康检查（含 schema_version）。ready→200 ok；未 ready→503 degraded。"""
    body, code = v2_service.health()
    return jsonify(body), code


# ============================================================
# 生成链路（POST /runs，同步执行 —— P0-4）
# ============================================================


def _parse_material_ids(raw, *, is_form: bool) -> list[int] | None:
    """解析 JSON 数组或 multipart 的 material_ids；非法输入抛 ValueError。"""
    if raw is None:
        return None
    if is_form:
        values = raw if isinstance(raw, list) else [raw]
        tokens: list[str] = []
        for value in values:
            tokens.extend(part.strip() for part in str(value).split(",") if part.strip())
        try:
            ids = [int(token) for token in tokens]
        except ValueError as exc:
            raise ValueError("material_ids 必须为整数数组") from exc
    else:
        if not isinstance(raw, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in raw):
            raise ValueError("material_ids 必须是整数数组")
        ids = list(raw)
    if not ids:
        return None
    if any(x <= 0 for x in ids):
        raise ValueError("material_ids 必须为正整数")
    ids = list(dict.fromkeys(ids))
    if len(ids) > v2_service.MAX_MATERIALS:
        raise ValueError(f"最多选择 {v2_service.MAX_MATERIALS} 个项目材料")
    return ids


@bp.route("/api/v2/runs", methods=["POST"])
@login_required
@csrf_protect
def v2_create_run():
    """创建 Run + 同步触发全链路（Step 2→8）。支持 JSON 与 multipart（文件上传）。

    错误分级（P0-3）：400 参数 / 401 未登录（login_required）/ 403 CSRF（csrf_protect）/
    503 V2 未 ready（before_request）/ 500 未捕获异常。
    Runtime FAILED 不塌缩：返回 200 + body 带 run_id/status=failed/failed_step/error_message。
    文件上传限制：最多 10 个，仅 md/txt/xlsx/xls/图片；PDF/Word 暂不支持。
    """
    is_multipart = bool(request.content_type and "multipart/form-data" in request.content_type)
    if is_multipart:
        title = (request.form.get("title") or "").strip()
        text = (request.form.get("text") or "").strip()
        source_type = request.form.get("source_type") or "text"
        files = [f for f in request.files.getlist("files") if f and f.filename]
        material_ids_raw = request.form.getlist("material_ids")
    else:
        data = request.get_json(silent=True)
        if not data:
            return jsonify({"error": "请求格式错误，请发送 JSON"}), 400
        title = (data.get("title") or "").strip()
        text = (data.get("text") or "").strip()
        source_type = data.get("source_type") or "text"
        files = []
        material_ids_raw = data.get("material_ids")

    if not title:
        return jsonify({"error": "title 不能为空"}), 400
    if not text and not files:
        return jsonify({"error": "text 或 files 至少提供一个"}), 400

    try:
        material_ids = _parse_material_ids(material_ids_raw, is_form=is_multipart)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    if files:
        if len(files) > v2_service.MAX_UPLOAD_FILES:
            return jsonify({"error": f"最多上传 {v2_service.MAX_UPLOAD_FILES} 个文件"}), 400
        for file in files:
            suffix = Path(file.filename or "").suffix.lower()
            if suffix not in v2_service.ALLOWED_UPLOAD_EXTS:
                return jsonify({"error": f"不支持的文件类型: {file.filename}（仅支持 md/txt/xlsx/xls/图片）"}), 400

    try:
        if files:
            with v2_service.uploaded_paths(files) as paths:
                upload_source_type = v2_service.derive_source_type(paths, text, source_type)
                result = v2_service.create_run_and_generate(
                    session["user_id"],
                    session.get("username", ""),
                    title,
                    text,
                    upload_source_type,
                    material_ids=material_ids,
                    paths=paths,
                )
        else:
            result = v2_service.create_run_and_generate(
                session["user_id"], session.get("username", ""), title, text, source_type, material_ids=material_ids
            )
    except Exception as e:  # 未捕获异常 → 500（P0-3）
        logger.exception("V2 POST /runs 执行异常")
        return jsonify({"error": f"V2 生成执行异常: {e}"}), 500
    return jsonify(result), 200


# ============================================================
# Run 查询接口
# ============================================================


@bp.route("/api/v2/runs", methods=["GET"])
@login_required
def v2_list_runs():
    """列出当前登录用户自己的 Run（Step 10.3.1，MVP：最近 N 条，默认 50）。

    与 POST /api/v2/runs 同路径不同方法（Flask 允许）：POST 触发生成，GET 查询列表。
    无 V2 user → items:[]（GET 不自动开通，避免读操作产生写副作用）。
    """
    return jsonify({"success": True, "items": v2_service.list_runs(session["user_id"])})


@bp.route("/api/v2/runs/<run_id>", methods=["GET"])
@login_required
def v2_get_run(run_id):
    detail = v2_service.get_run_detail(run_id)
    if detail is None:
        return jsonify({"error": f"Run 不存在: {run_id}"}), 404
    return jsonify({"success": True, "run": detail})


@bp.route("/api/v2/runs/<run_id>/test-points", methods=["GET"])
@login_required
def v2_list_test_points(run_id):
    if not v2_service.run_exists(run_id):
        return jsonify({"error": f"Run 不存在: {run_id}"}), 404
    provenance = request.args.get("provenance")
    return jsonify({"success": True, "test_points": v2_service.list_test_points(run_id, provenance)})


@bp.route("/api/v2/runs/<run_id>/test-cases", methods=["GET"])
@login_required
def v2_list_test_cases(run_id):
    if not v2_service.run_exists(run_id):
        return jsonify({"error": f"Run 不存在: {run_id}"}), 404
    status = request.args.get("status")
    return jsonify({"success": True, "test_cases": v2_service.list_test_cases(run_id, status)})


@bp.route("/api/v2/runs/<run_id>/review", methods=["GET"])
@login_required
def v2_get_review(run_id):
    if not v2_service.run_exists(run_id):
        return jsonify({"error": f"Run 不存在: {run_id}"}), 404
    return jsonify({"success": True, "review": v2_service.get_review_report(run_id)})


@bp.route("/api/v2/runs/<run_id>/optimizer", methods=["GET"])
@login_required
def v2_get_optimizer(run_id):
    if not v2_service.run_exists(run_id):
        return jsonify({"error": f"Run 不存在: {run_id}"}), 404
    return jsonify({"success": True, "optimizer": v2_service.get_optimizer_result(run_id)})


@bp.route("/api/v2/runs/<run_id>/coverage", methods=["GET"])
@login_required
def v2_get_coverage(run_id):
    if not v2_service.run_exists(run_id):
        return jsonify({"error": f"Run 不存在: {run_id}"}), 404
    return jsonify({"success": True, "coverage": v2_service.get_coverage(run_id)})


@bp.route("/api/v2/runs/<run_id>/requirements", methods=["GET"])
@login_required
def v2_get_requirements(run_id):
    """需求与 AI 分析（只读，Step 11 UI 重构）：Doc + Version + RequirementItem 列表。

    仅供 V2 前端展示 Requirement IR；不改 schema / Runtime / Run 数据结构。
    """
    ctx = v2_service.get_requirements_context(run_id)
    if ctx is None:
        return jsonify({"error": f"Run 不存在: {run_id}"}), 404
    return jsonify({"success": True, "requirements": ctx})


@bp.route("/api/v2/runs/<run_id>/export", methods=["GET"])
@login_required
def v2_export_run(run_id):
    """导出当前用户自己的 Run（Step 12.1）：format=xlsx|md，默认排除 ARCHIVED 用例。

    归属不匹配按 404 处理（不暴露他人 Run 是否存在）。
    """
    fmt = request.args.get("format") or "xlsx"
    try:
        result = v2_service.export_run(session["user_id"], run_id, fmt)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if result is None:
        return jsonify({"error": f"Run 不存在: {run_id}"}), 404
    data, mimetype, filename = result
    return send_file(BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=filename)


# ============================================================
# TestCase 人工操作（Step 9）+ 追溯（Step 6）—— 用户后续主动操作
# ============================================================


@bp.route("/api/v2/test-cases/<tc_id>/edit", methods=["POST"])
@login_required
@csrf_protect
def v2_edit_test_case(tc_id):
    """人工编辑（带乐观锁 expected_updated_at）。404 不存在 / 409 冲突 / 200 结果。"""
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "请求格式错误，请发送 JSON"}), 400
    updates = data.get("updates") or {}
    expected = data.get("expected_updated_at")
    try:
        result = v2_service.edit_test_case(tc_id, updates, expected)
    except repo.ConcurrentModificationError as e:
        return jsonify({"error": str(e)}), 409
    if result is None:
        return jsonify({"error": f"TestCase 不存在: {tc_id}"}), 404
    return jsonify({"success": bool(result.get("success")), "result": result})


@bp.route("/api/v2/test-cases/<tc_id>/re-review", methods=["POST"])
@login_required
@csrf_protect
def v2_re_review(tc_id):
    """用户主动触发 AFTER_HUMAN_EDIT 重评审（Step 9）。run_id 缺省时从 TestCase 反查。"""
    data = request.get_json(silent=True) or {}
    run_id = data.get("run_id")
    if not run_id:
        tc = repo.get_test_case(tc_id)
        if tc is None:
            return jsonify({"error": f"TestCase 不存在: {tc_id}"}), 404
        run_id = tc.run_id
    tc_ids = data.get("test_case_ids") or [tc_id]
    try:
        result = v2_service.re_review(run_id, tc_ids)
    except Exception as e:
        logger.exception("V2 re-review 执行异常")
        return jsonify({"error": f"重评审执行异常: {e}"}), 500
    return jsonify({"success": True, "result": result})


@bp.route("/api/v2/test-cases/<tc_id>/revisions", methods=["GET"])
@login_required
def v2_list_revisions(tc_id):
    if not v2_service.test_case_exists(tc_id):
        return jsonify({"error": f"TestCase 不存在: {tc_id}"}), 404
    return jsonify({"success": True, "revisions": v2_service.list_revisions(tc_id)})


@bp.route("/api/v2/test-cases/<tc_id>/trace", methods=["GET"])
@login_required
def v2_trace(tc_id):
    if not v2_service.test_case_exists(tc_id):
        return jsonify({"error": f"TestCase 不存在: {tc_id}"}), 404
    return jsonify({"success": True, "trace": v2_service.trace_test_case(tc_id)})
