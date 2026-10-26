// ============================================================
// 测试点页（简洁视图）：按模块/子分类展示，默认隐藏工程统计；
// 支持导出 XMind，工程细节收进「工程详情」。
// ============================================================

import { useMemo, useState } from "react";
import { downloadTestPointsXmind } from "../api/v2";
import { useToast } from "../components/Toast";
import { useRunBundle } from "./RunBundle";
import type { TestPoint } from "../types";

export function TestPointsTab() {
  const { testPoints, run } = useRunBundle();
  const toast = useToast();
  const [q, setQ] = useState("");
  const [mod, setMod] = useState("");
  const [exporting, setExporting] = useState(false);

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

  return (
    <div>
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
        <button className="btn btn-sm btn-primary" onClick={doExport} disabled={exporting || !testPoints.length}>
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
                      <div className="testpoint-title">
                        {point.title} <span className="t-aux">{point.priority}</span>
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
    </div>
  );
}
