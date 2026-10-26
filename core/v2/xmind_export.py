"""V2 测试点 XMind 导出 - 生成 XMind 8+ JSON 格式的 .xmind 文件。"""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from io import BytesIO

from core.schemas import TestPoint


def _enum_value(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def _topic(node_id: str, title: str, children: list[dict] | None = None) -> dict:
    node = {"id": node_id, "class": "topic", "title": title}
    if children:
        node["children"] = {"attached": children}
    return node


def _test_point_topic(point: TestPoint) -> dict:
    children = [
        _topic(f"{point.id}_desc", f"描述：{point.description}"),
        _topic(f"{point.id}_priority", f"优先级：{_enum_value(point.priority)}"),
        _topic(f"{point.id}_dimension", f"维度：{_enum_value(point.dimension)}"),
    ]
    return _topic(point.id, point.title, children)


def export_test_points_xmind(
    test_points: list[TestPoint],
    *,
    run_title: str,
    exported_at: datetime | None = None,
) -> bytes:
    """把测试点组织为「需求 → 模块 → 子分类 → 测试点」的 XMind 文件。"""
    exported_at = exported_at or datetime.now()
    modules: dict[str, dict[str, list[TestPoint]]] = {}
    for point in test_points:
        modules.setdefault(point.module or "未分类", {}).setdefault(point.subcategory or "未分类", []).append(point)

    module_topics: list[dict] = []
    for module_idx, (module, subcategories) in enumerate(modules.items(), 1):
        subcategory_topics: list[dict] = []
        for sub_idx, (subcategory, points) in enumerate(subcategories.items(), 1):
            subcategory_topics.append(
                _topic(
                    f"sub_{module_idx}_{sub_idx}",
                    subcategory,
                    [_test_point_topic(point) for point in points],
                )
            )
        module_topics.append(_topic(f"module_{module_idx}", module, subcategory_topics))

    content = [
        {
            "id": "sheet_1",
            "class": "sheet",
            "title": "测试点",
            "rootTopic": {
                "id": "root",
                "class": "topic",
                "title": run_title,
                "structureClass": "org.xmind.ui.map.unbalanced",
                "children": {"attached": module_topics},
            },
        }
    ]
    metadata = {
        "creator": {
            "name": "AI Test Case Generation Assistant Platform",
            "version": "1.0.0",
        },
        "exported_at": exported_at.isoformat(),
    }
    manifest = {"file-entries": {"content.json": {}, "metadata.json": {}}}

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("content.json", json.dumps(content, ensure_ascii=False, indent=2))
        zf.writestr("metadata.json", json.dumps(metadata, ensure_ascii=False))
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    return buf.getvalue()
