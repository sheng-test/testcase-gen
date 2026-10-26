// ============================================================
// 测试点页（简洁视图）：按模块/子分类展示，默认隐藏工程统计；
// 支持导出 XMind，工程细节收进「工程详情」。
// ============================================================

import { useMemo, useState } from "react";
import { downloadTestPointsXmind, editTestPoint, generateTestCases } from "../api/v2";
import { useToast } from "../components/Toast";
import { useRunBundle } from "./RunBundle";
import type { TestPoint } from "../types";

export function TestPointsTab() {
  const { testPoints, testCases, run, reload } = useRunBundle();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [mod, setMod] = useState("");
  const [exporting, setExporting] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [editing, setEditing] = useState<TestPoint | null>(null);
  const locked = testCases.length > 0;

  const modules = useMemo(() => [...new Set(testPoints.map((p) => p.module).filter(Boolean))].sort(), [testPoints]);

  const filtered = testPoints.filter((p) => {
    if (mod && p.module !== mod) return false;
    if (q && !`${p.title}${p.description}${p.subcategory}`.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });

  const grouped = useMemo(() => {
    const byModule = new Map<string, Map<string, TestPoint[]>>();
    filtered.forEach((p) => {
      const module = p.module || "未分类";
      const subcategory = p.subcategory || "未分类";
      const subMap = byModule.get(module) || new Map<string, TestPoint[]>();
      const points = subMap.get(subcategory) || [];
      points.push(p);
      subMap.set(subcategory, points);
      byModule.set(module, subMap);
    });
    return [...byModule.entries()];
  }, [filtered]);

  const stats = useMemo(() => {
    const llm = testPoints.filter((p) => (p.provenance || "").toUpperCase() === "LLM").length;
    const strategy = testPoints.filter((p) => (p.provenance || "").toUpperCase() === "STRATEGY").length;
    const scope = new Map<string, number>();
    testPoints.forEach((p) => {
      const s = p.generation_scope || "item";
      scope.set(s, (scope.get(s) || 0) + 1);
    });
    return { llm, strategy, scope };
  }, [testPoints]);

  const doExport = async () => {
    setExporting(true);
    try {
      await downloadTestPointsXmind(run.id);
      toast("测试点已导出 XMind");
    } catch (e) {
      toast(e instanceof Error ? e.message : "导出失败", "error");
    } finally {
      setExporting(false);
    }
  };

  const doGenerateCases = async () => {
    if (!window.confirm(`将基于当前 ${testPoints.length} 个测试点生成用例并触发 AI 评审，可能需要数十秒，确认继续？`)) return;
    setGenerating(true);
    try {
      const result = await generateTestCases(run.id);
      if (result.success === false || result.status === "failed") {
        toast(`生成未完成：${result.error_message || "未知错误"}`, "error");
      } else {
        toast(`测试用例已生成：${result.test_case_count ?? "-"} 条`);
        reload();
      }
    } catch (e) {
      toast(e instanceof Error ? e.message : "生成测试用例失败", "error");
    } finally {
      setGenerating(false);
    }
  };

  return (
    <div>
      {locked ? (
        <div className="alert alert-info">已生成测试用例，测试点已锁定；如需修改测试点，请新建运行。</div>
      ) : null}
      <div className="quick-toolbar">
        <span className="quick-title">{testPoints.length} 个测试点</span>
        <span className="t-aux">覆盖 {modules.length} 个模块</span>
        <span style={{ flex: 1 }} />
        <input
          type="search"
          placeholder="搜索标题/描述/子分类..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <select value={mod} onChange={(e) => setMod(e.target.value)}>
          <option value="">全部模块</option>
          {modules.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
        {!locked && testPoints.length ? (
          <button className="btn btn-sm btn-primary" onClick={doGenerateCases} disabled={generating || exporting}>
            {generating ? "生成中..." : "生成测试用例"}
          </button>
        ) : null}
        <button className="btn btn-sm btn-outline" onClick={doExport} disabled={exporting || !testPoints.length}>
          {exporting ? "导出中..." : "导出 XMind"}
        </button>
      </div>

      {grouped.length ? (
        grouped.map(([module, subcategories]) => {
          const count = [...subcategories.values()].reduce((n, points) => n + points.length, 0);
          return (
            <div className="quick-card" key={module}>
              <div className="quick-card-head">
                <h3>{module}</h3>
                <span className="meta">{count} 个测试点</span>
              </div>
              {[...subcategories.entries()].map(([subcategory, points]) => (
                <div className="testpoint-group" key={subcategory}>
                  <h4>{subcategory}</h4>
                  {points.map((point) => (
                    <div className="testpoint-item" key={point.id}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div className="testpoint-title" style={{ flex: 1 }}>
                          {point.title} <span className="t-aux">{point.priority}</span>
                        </div>
                        {!locked ? (
                          <button className="btn btn-sm btn-ghost" onClick={() => setEditing(point)}>
                            编辑
                          </button>
                        ) : null}
                      </div>
                      <div className="testpoint-desc">{point.description}</div>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          );
        })
      ) : (
        <div className="empty">无匹配测试点。</div>
      )}

      <details className="engineering-details">
        <summary>工程详情（来源 / 生成范围）</summary>
        <div className="quick-summary" style={{ marginTop: 8 }}>
          <span>
            LLM 语义设计 <b>{stats.llm}</b>
          </span>
          <span>
            策略补充 <b>{stats.strategy}</b>
          </span>
          <span>
            逐项 <b>{stats.scope.get("item") ?? 0}</b>
          </span>
          <span>
            跨项 <b>{stats.scope.get("cross_item") ?? 0}</b>
          </span>
        </div>
      </details>
      {editing ? (
        <TestPointEditModal
          point={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}

function TestPointEditModal({
  point,
  onClose,
  onSaved,
}: {
  point: TestPoint;
  onClose: () => void;
  onSaved: () => void;
}) {
  const toast = useToast();
  const [title, setTitle] = useState(point.title);
  const [description, setDescription] = useState(point.description);
  const [module, setModule] = useState(point.module);
  const [subcategory, setSubcategory] = useState(point.subcategory);
  const [priority, setPriority] = useState(point.priority || "P1");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await editTestPoint(point.id, { title, description, module, subcategory, priority });
      toast("测试点已保存");
      onSaved();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-head">
          <h3>编辑测试点</h3>
          <button className="modal-close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">
          <div className="form-group">
            <label>标题</label>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
          </div>
          <div className="form-group">
            <label>描述</label>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="form-group">
            <label>模块</label>
            <input type="text" value={module} onChange={(e) => setModule(e.target.value)} />
          </div>
          <div className="form-group">
            <label>子分类</label>
            <input type="text" value={subcategory} onChange={(e) => setSubcategory(e.target.value)} />
          </div>
          <div className="form-group">
            <label>优先级</label>
            <select value={priority} onChange={(e) => setPriority(e.target.value)}>
              {["P0", "P1", "P2", "P3"].map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </div>
          {err ? <div className="alert alert-error">{err}</div> : null}
        </div>
        <div className="modal-foot">
          <button className="btn btn-ghost" onClick={onClose}>
            取消
          </button>
          <button className="btn btn-primary" onClick={save} disabled={busy}>
            {busy ? "保存中..." : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
