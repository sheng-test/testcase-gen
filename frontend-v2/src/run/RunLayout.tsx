// ============================================================
// 运行详情布局：主视图只保留需求 / 测试点 / 测试用例；
// IR、优化、报告等工程细节收进「高级」入口，降低默认信息密度。
// ============================================================

import { NavLink, Outlet, useParams } from "react-router-dom";
import { Shell } from "../layout/Shell";
import { RunBundleProvider, useRunBundle } from "./RunBundle";
import { CaseDrawer } from "./CaseDrawer";
import { RunStatusBadge } from "../components/ui";

export function RunLayout() {
  const { runId } = useParams<{ runId: string }>();
  if (!runId) return null;
  return (
    <RunBundleProvider runId={runId}>
      <RunLayoutInner />
    </RunBundleProvider>
  );
}

function RunLayoutInner() {
  const { run, title, testPoints, testCases, review, optimizer } = useRunBundle();
  const base = `/runs/${run.id}`;
  const primaryTabs = [
    { to: `${base}/requirements`, label: "需求", count: run.counts?.items },
    { to: `${base}/test-points`, label: "测试点", count: testPoints.length },
    { to: `${base}/test-cases`, label: "测试用例", count: testCases.length },
  ];
  const advancedTabs = [
    { to: base, label: "概览", end: true },
    { to: `${base}/review`, label: "AI 评审详情", count: review?.findings?.length, end: false },
    { to: `${base}/optimizer`, label: "去重优化", count: optimizer?.archived_count, end: false },
    { to: `${base}/report`, label: "报告", end: false },
  ];
  return (
    <Shell
      crumbs={
        <>
          <NavLink to="/runs">测试运行</NavLink> <span>/</span> <b>{title}</b>
        </>
      }
    >
      <div className="page">
        <div className="page-header">
          <div className="ph-main">
            <h2>
              {title} <RunStatusBadge status={run.status} />
            </h2>
            <div className="ph-desc">需求 → 测试点 → 测试用例；AI 评审与工程细节在「高级」入口。</div>
          </div>
          <div className="ph-actions no-print">
            <button className="btn btn-sm btn-outline" onClick={() => window.print()}>
              打印 / 导出 PDF
            </button>
          </div>
        </div>
        <div className="tabs no-print">
          {primaryTabs.map((t) => (
            <NavLink key={t.to} className={({ isActive }) => `tab${isActive ? " active" : ""}`} to={t.to}>
              {t.label}
              {t.count != null ? <span className="tab-count">{t.count}</span> : null}
            </NavLink>
          ))}
          <span style={{ flex: 1 }} />
          <details className="advanced-tabs">
            <summary className="tab">高级 ▾</summary>
            <div className="advanced-panel">
              {advancedTabs.map((t) => (
                <NavLink
                  key={t.to}
                  className={({ isActive }) => `advanced-link${isActive ? " active" : ""}`}
                  to={t.to}
                  end={t.end}
                  onClick={(e) => e.currentTarget.closest("details")?.removeAttribute("open")}
                >
                  {t.label}
                  {t.count != null ? <span className="tab-count">{t.count}</span> : null}
                </NavLink>
              ))}
            </div>
          </details>
        </div>
        <Outlet />
      </div>
      <CaseDrawer />
    </Shell>
  );
}
