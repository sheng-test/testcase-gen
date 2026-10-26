// ============================================================
// 资源 · XMind 导出说明：测试点导出在 V2 运行页内完成，不跳转 V1。
// ============================================================

import { Link } from "react-router-dom";
import { Card } from "../components/ui";
import { Shell } from "../layout/Shell";

export function XmindPage() {
  return (
    <Shell crumbs={<><span>资源</span> <span>/</span> <b>XMind 导出</b></>}>
      <div className="page" style={{ maxWidth: 860 }}>
        <div className="page-header">
          <div className="ph-main">
            <h2>XMind 导出</h2>
            <div className="ph-desc">测试点可直接导出 XMind，全部操作在 V2 运行页完成。</div>
          </div>
        </div>

        <Card title="导出测试点到 XMind">
          <p className="small">打开任意测试运行 →「测试点」→ 点击「导出 XMind」。导出结构：</p>
          <pre className="field-block" style={{ background: "var(--bg-elevated)", padding: 10, borderRadius: 6, fontSize: 12 }}>
            需求标题 → 模块 → 子分类 → 测试点 → 描述 / 优先级 / 维度
          </pre>
          <Link className="btn btn-outline" to="/runs">
            进入测试运行 →
          </Link>
        </Card>

        <Card title="V1 历史数据迁移到 V2（CLI）">
          <p className="small">
            迁移遵循「不猜历史关系、未知=NULL、provenance=migrated」铁律，由后端脚本执行：
          </p>
          <pre className="field-block" style={{ background: "var(--bg-elevated)", padding: 10, borderRadius: 6, fontSize: 12 }}>
            python -m core.v2.migrate_v1_to_v2
          </pre>
          <div className="muted small">迁移用例在 V2 运行中以「MIGRATED」来源标识呈现，不伪造测试点关联。</div>
        </Card>
      </div>
    </Shell>
  );
}
