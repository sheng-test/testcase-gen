// ============================================================
// 新建测试运行（阶段 A 入口）。
// ★ 同步 MVP 诚实呈现：POST /api/v2/runs 同步等待全链路完成（可能数分钟），
//   无 SSE / 轮询 / 后台 Job（Step 10 冻结限制）；失败不塌缩，展示 failed_step。
// ★ 项目材料：Step 12.2 起可选择材料作为背景上下文（最多 5 个，仅文本）。
// ============================================================

import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { listMaterials } from "../api/v1";
import { createRun } from "../api/v2";
import { Shell } from "../layout/Shell";
import { useToast } from "../components/Toast";
import { STEP_LABEL } from "../utils";
import type { MaterialListItem } from "../types";

export function RunNew() {
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [materials, setMaterials] = useState<MaterialListItem[] | null>(null);
  const [materialIds, setMaterialIds] = useState<number[]>([]);
  const [running, setRunning] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [failedRunId, setFailedRunId] = useState<string | null>(null);
  const toast = useToast();
  const nav = useNavigate();

  useEffect(() => {
    listMaterials()
      .then(setMaterials)
      .catch(() => setMaterials([]));
  }, []);

  const toggleMaterial = (id: number) => {
    if (materialIds.includes(id)) {
      setMaterialIds(materialIds.filter((x) => x !== id));
      return;
    }
    if (materialIds.length >= 5) {
      toast("最多选择 5 个项目材料", "warn");
      return;
    }
    setMaterialIds([...materialIds, id]);
  };

  const start = async () => {
    if (!title.trim() || !text.trim()) {
      toast("请填写需求标题与需求描述", "warn");
      return;
    }
    setRunning(true);
    setErr(null);
    setFailedRunId(null);
    try {
      const d = await createRun(title.trim(), text.trim(), "text", materialIds);
      if (d.success === false || d.status === "failed") {
        setErr(
          `运行未完成：失败于「${STEP_LABEL[d.failed_step || ""] || d.failed_step || "未知阶段"}」——${d.error_message || "无错误详情"}`,
        );
        setFailedRunId(d.run_id || null);
        toast("生成未完成，可查看失败详情", "error");
        return;
      }
      toast(`运行完成：测试点 ${d.test_point_count ?? "-"} · 用例 ${d.test_case_count ?? "-"}`);
      if (d.run_id) nav(`/runs/${d.run_id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "请求异常");
    } finally {
      setRunning(false);
    }
  };

  return (
    <Shell crumbs={<><Link to="/runs">测试运行</Link> <span>/</span> <b>新建</b></>}>
      <div className="page" style={{ maxWidth: 780 }}>
        <div className="page-header">
          <div className="ph-main">
            <h2>新建测试运行</h2>
            <div className="ph-desc">输入一份需求，AI 将自动完成：解析需求 → 设计测试点 → 策略补充 → 合成用例 → 评审 → 去重。</div>
          </div>
        </div>

        <div className="card">
          <div className="card-body">
            <div className="form-group">
              <label>① 需求标题</label>
              <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="如：订单退款申请" disabled={running} />
            </div>
            <div className="form-group">
              <label>② 需求内容（Markdown / 纯文本）</label>
              <textarea
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="粘贴需求文档内容..."
                style={{ minHeight: 220 }}
                disabled={running}
              />
            </div>
            <div className="form-group">
              <label>③ 项目材料（可选，最多 5 个）</label>
              {materials === null ? (
                <div className="t-aux">加载中...</div>
              ) : materials.length ? (
                <div className="material-picker">
                  {materials.map((m) => (
                    <label key={m.id} className="material-option">
                      <input
                        type="checkbox"
                        checked={materialIds.includes(m.id)}
                        onChange={() => toggleMaterial(m.id)}
                        disabled={running}
                      />
                      <span>
                        <span className="material-option-title">{m.title}</span>
                        <span className="material-option-preview">{m.content_preview || "（无文本内容）"}</span>
                      </span>
                    </label>
                  ))}
                </div>
              ) : (
                <div className="t-aux">暂无项目材料，可先在「资源 · 项目材料」中创建。</div>
              )}
              <div className="hint muted small" style={{ marginTop: 6 }}>
                已选 {materialIds.length}/5；材料作为背景上下文参与需求解析，当前仅引用文本内容。
              </div>
              <Link className="btn btn-sm btn-ghost" to="/resources/materials">
                去管理项目材料 →
              </Link>
            </div>
            {err ? (
              <div className="alert alert-error">
                {err}
                {failedRunId ? (
                  <div style={{ marginTop: 6 }}>
                    <Link className="btn btn-sm btn-outline" to={`/runs/${failedRunId}`}>
                      查看该运行详情
                    </Link>
                  </div>
                ) : null}
              </div>
            ) : null}
            <hr className="divider" />
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <button className="btn btn-primary" onClick={start} disabled={running}>
                {running ? "全链路执行中..." : "▶ 开始生成"}
              </button>
              {running ? <span className="spinner" /> : null}
            </div>
            <div className="hint muted small" style={{ marginTop: 10 }}>
              执行为同步模式（当前 Web MVP 已知限制）：整个链路需要数分钟，请保持页面打开、勿重复点击；若页面被刷新，已完成的运行仍可在运行列表中找回。
              需要权威长链路验证时请使用 CLI（scripts/v2_real_run.py）。
            </div>
          </div>
        </div>
      </div>
    </Shell>
  );
}
