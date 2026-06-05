"""
Ontology Demo — FastAPI 主入口

启动: python server.py
然后访问 http://localhost:8000 查看前端页面
Swagger 文档: http://localhost:8000/docs

NL 查询实现分别在:
  nl_batch.py  — Batch Plan 模式
  nl_graph.py  — Graph Walk 模式
  nl_oag.py    — OAG（Ontology Augmented Generation）模式
"""

from __future__ import annotations
from fastapi import FastAPI, Query, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

from ontology_engine.database import init_db, get_connection
from ontology_engine.registry import OBJECT_TYPES, LINK_TYPES, ACTION_TYPES, FUNCTIONS, INTERFACES, OBJECT_SETS
from ontology_engine.query import get_object, query_objects, traverse_link, query_objects_v2, query_object_set, fill_derived_batch
from ontology_engine.action import execute_action
from ontology_engine.functions import call_function, compute_derived_property
from ontology_engine.graph import get_graph, reload_graph

# NL 查询模块
from nl_batch import handle_batch_query
from nl_graph import handle_graph_query
from nl_oag import handle_oag_query

app = FastAPI(title="Ontology Demo", description="学生成绩管理系统 — Ontology 语义层 Demo")

# ---- 启动时初始化 ----

@app.on_event("startup")
def startup():
    init_db()


# ============================================================
# Schema 元数据 API（供前端和 AI Agent 使用）
# ============================================================

@app.get("/ontology/schema")
def get_schema():
    """返回完整 Ontology Schema，供前端图谱渲染和 LLM Tool Definition 使用"""
    objects = {}
    for name, o in OBJECT_TYPES.items():
        objects[name] = {
            "apiName": o.api_name,
            "displayName": o.display_name,
            "table": o.table,
            "properties": [
                {"name": p.name, "type": p.prop_type, "dataType": p.data_type}
                for p in o.properties
            ],
        }

    links = {}
    for name, l in LINK_TYPES.items():
        links[name] = {
            "apiName": l.api_name,
            "displayName": l.display_name,
            "sourceType": l.source_type,
            "targetType": l.target_type,
            "cardinality": l.cardinality,
            "reverseName": l.reverse_name,
        }

    actions = {}
    for name, a in ACTION_TYPES.items():
        actions[name] = {
            "apiName": a.api_name,
            "displayName": a.display_name,
            "actionType": a.action_type,
            "boundObject": a.bound_object,
            "params": [{"name": p.name, "type": p.param_type, "required": p.required} for p in a.params],
        }

    functions = {}
    for name, f in FUNCTIONS.items():
        functions[name] = {
            "apiName": f.api_name,
            "displayName": f.display_name,
            "funcType": f.func_type,
            "boundObject": f.bound_object,
            "returnType": f.return_type,
            "params": [{"name": p.name, "type": p.param_type, "required": p.required} for p in f.params],
        }

    return {"objects": objects, "links": links, "actions": actions, "functions": functions}


# ============================================================
# Object 查询 API
# ============================================================

@app.get("/ontology/objects/{object_type}")
def api_query_objects(
    object_type: str,
    name: Optional[str] = Query(None),
    order_by: Optional[str] = Query(None),
    order_dir: str = Query("asc"),
    limit: int = Query(50),
    offset: int = Query(0),
):
    """查询对象列表，支持 name 模糊匹配"""
    where = {"name": name} if name else None
    results = query_objects(object_type, where=where, order_by=order_by,
                            order_dir=order_dir, limit=limit, offset=offset)
    # 计算派生属性
    for obj in results:
        _fill_derived(object_type, obj)
    return {"data": results, "count": len(results)}


@app.get("/ontology/objects/{object_type}/{object_id}")
def api_get_object(object_type: str, object_id: int):
    """获取单个对象（含派生属性）"""
    obj = get_object(object_type, object_id)
    if obj is None:
        raise HTTPException(404, f"{object_type} id={object_id} not found")
    _fill_derived(object_type, obj)
    return obj


@app.get("/ontology/objects/{object_type}/{object_id}/links/{link_name}")
def api_traverse_link(object_type: str, object_id: int, link_name: str):
    """沿 Link 遍历获取关联对象"""
    results = traverse_link(object_type, object_id, link_name)
    return {"data": results, "count": len(results)}


# ============================================================
# Function API
# ============================================================

@app.get("/ontology/functions/{func_name}")
def api_call_function(func_name: str, request: Request):
    """调用 Function——动态接收所有 query 参数"""
    params = {}
    for key, val in request.query_params.items():
        # 自动转换数值类型
        if val.isdigit():
            params[key] = int(val)
        elif val.replace('.', '', 1).replace('-', '', 1).isdigit():
            params[key] = float(val)
        else:
            params[key] = val
    return call_function(func_name, params)


# ============================================================
# Action API
# ============================================================

class ActionRequest(BaseModel):
    params: dict


@app.post("/ontology/actions/{action_name}")
def api_execute_action(action_name: str, req: ActionRequest):
    """执行 Action"""
    result = execute_action(action_name, req.params)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Action failed"))
    return result


# ============================================================
# ObjectSet API
# ============================================================

@app.get("/ontology/object-sets")
def api_list_object_sets():
    """列出所有 ObjectSet 定义"""
    result = {}
    for name, os_def in OBJECT_SETS.items():
        result[name] = {
            "apiName": os_def.api_name,
            "displayName": os_def.display_name,
            "objectType": os_def.object_type,
            "description": os_def.description,
        }
    return result


@app.get("/ontology/object-sets/{set_name}")
def api_query_object_set(set_name: str, limit: int = Query(50)):
    """查询 ObjectSet 中的对象"""
    result = query_object_set(set_name, limit=limit)
    if not result.get("success"):
        raise HTTPException(404, result.get("error", "ObjectSet not found"))
    return result


@app.get("/ontology/tables")
def api_list_tables():
    """返回所有原始数据表的结构和数据（用于前端展示底层 SQL 数据）"""
    tables = {}
    for table_name in ["student", "teacher", "course", "score", "audit_log"]:
        conn = get_connection()
        # 获取列信息
        cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = [{"name": c["name"], "type": c["type"], "pk": bool(c["pk"])} for c in cols]
        # 获取数据（限制行数）
        rows = conn.execute(f"SELECT * FROM {table_name} LIMIT 100").fetchall()
        data = [dict(r) for r in rows]
        conn.close()
        tables[table_name] = {"columns": columns, "data": data, "row_count": len(data)}
    return {"success": True, "tables": tables}


# ============================================================
# 自然语言查询 API（实现分别在 nl_batch.py / nl_graph.py / nl_oag.py）
# ============================================================

import json


@app.post("/ontology/nl-query")
async def api_nl_query(req: dict):
    """Batch Plan 模式：LLM 输出完整 JSON 操作序列，引擎逐条执行。"""
    return await handle_batch_query(req.get("query", ""))


@app.post("/ontology/nl-query-graph")
async def api_nl_query_graph(req: dict):
    """Graph Walk 模式：LLM 通过工具在内存实例图谱上逐步游走探索。"""
    return await handle_graph_query(
        req.get("query", ""),
        max_iterations=req.get("max_iterations", 20),
    )


@app.post("/ontology/nl-query-oag")
async def api_nl_query_oag(req: dict):
    """OAG 模式：LLM 在对象类型层操作，引擎负责 Link JOIN 编译和派生属性自动计算。"""
    return await handle_oag_query(
        req.get("query", ""),
        max_iterations=req.get("max_iterations", 20),
    )


# ============================================================
# 图谱数据 API（全量对象+关系，供前端渲染）
# ============================================================

@app.get("/ontology/graph")
def api_graph_data():
    """返回全量图谱数据：节点（所有 Object）+ 边（所有 Link）"""
    nodes = []
    edges = []

    for obj_name, obj_def in OBJECT_TYPES.items():
        # 获取所有对象
        conn = __import__("ontology_engine.database", fromlist=["get_connection"]).get_connection()
        rows = conn.execute(f"SELECT * FROM {obj_def.table}").fetchall()
        conn.close()

        for row in rows:
            nodes.append({
                "id": f"{obj_name}-{row['id']}",
                "objectType": obj_name,
                "objectId": row["id"],
                "label": row["name"] if "name" in row.keys() else f"{obj_name}#{row['id']}",
                "group": obj_name,
            })

    for link_def in LINK_TYPES.values():
        source_def = OBJECT_TYPES[link_def.source_type]
        conn = __import__("ontology_engine.database", fromlist=["get_connection"]).get_connection()
        rows = conn.execute(f"SELECT id, {link_def.source_fk} FROM {source_def.table}").fetchall()
        conn.close()

        for row in rows:
            source_id = row["id"]
            target_id = row[link_def.source_fk]
            if target_id:
                edges.append({
                    "from": f"{link_def.source_type}-{source_id}",
                    "to": f"{link_def.target_type}-{target_id}",
                    "label": link_def.api_name,
                    "displayLabel": link_def.display_name,
                })

    return {"nodes": nodes, "edges": edges}


@app.get("/ontology/graph/schema")
def api_schema_graph():
    """返回 Ontology 类型层图谱：Object Type 为节点，Link Type 为边"""
    nodes = []
    edges = []

    # 每个 Object Type 是一个节点
    for name, obj_def in OBJECT_TYPES.items():
        props_summary = ", ".join(
            f"{p.name}({p.data_type})" for p in obj_def.properties[:4]
        )
        nodes.append({
            "id": f"Type-{name}",
            "label": f"{obj_def.display_name}\n{name}",
            "group": name,
            "title": f"<b>{obj_def.display_name} ({name})</b><br>"
                     f"表: {obj_def.table}<br>"
                     f"属性: {props_summary}",
            "shape": "box",
            "size": 35,
            "font": {"size": 14, "color": "#333", "multi": True},
            "borderWidth": 2,
            "level": 0,
        })

    # 每个 Link Type 是一条边
    for name, link_def in LINK_TYPES.items():
        edges.append({
            "from": f"Type-{link_def.source_type}",
            "to": f"Type-{link_def.target_type}",
            "label": f"{link_def.display_name}\n({link_def.api_name})",
            "arrows": "to",
            "font": {"size": 11, "color": "#555", "background": "white", "multi": True},
            "width": 2,
            "color": {"color": "#888", "opacity": 0.8},
        })

    # Interface 节点（菱形，紫色，level=1 便于分层布局）
    if INTERFACES:
        for name, iface_def in INTERFACES.items():
            nodes.append({
                "id": f"Interface-{name}",
                "label": f"◆ {iface_def.display_name}\n{name}",
                "group": "Interface",
                "title": f"<b>{iface_def.display_name} ({name})</b><br>"
                         f"{iface_def.description}<br>"
                         f"共享属性: {', '.join(iface_def.shared_properties) if iface_def.shared_properties else '无'}<br>"
                         f"共享Function: {', '.join(iface_def.shared_functions)}<br>"
                         f"实现者: {', '.join(iface_def.implementors)}",
                "shape": "diamond",
                "size": 30,
                "color": {"background": "#f9f0ff", "border": "#722ed1"},
                "font": {"size": 12, "color": "#531dab", "multi": True},
                "borderWidth": 2,
                "level": 1,
            })
            # implements 边（虚线）
            for impl in iface_def.implementors:
                edges.append({
                    "from": f"Interface-{name}",
                    "to": f"Type-{impl}",
                    "label": "implements",
                    "arrows": "to",
                    "dashes": [8, 4],
                    "font": {"size": 9, "color": "#999", "background": "white"},
                    "width": 1,
                    "color": {"color": "#b37feb", "opacity": 0.6},
                })

    return {"nodes": nodes, "edges": edges}


@app.get("/ontology/interfaces")
def api_interfaces():
    """返回所有 Interface 定义"""
    result = {}
    for name, iface_def in INTERFACES.items():
        result[name] = {
            "apiName": iface_def.api_name,
            "displayName": iface_def.display_name,
            "description": iface_def.description,
            "sharedProperties": iface_def.shared_properties,
            "sharedFunctions": iface_def.shared_functions,
            "implementors": iface_def.implementors,
        }
    return result


def _fill_derived(object_type: str, obj: dict):
    """为对象填充派生属性"""
    obj_id = obj.get("id")
    if obj_id is None:
        return
    obj_def = OBJECT_TYPES.get(object_type)
    if not obj_def:
        return
    for p in obj_def.properties:
        if p.prop_type == "derived":
            val = compute_derived_property(object_type, obj_id, p.name)
            obj[p.name] = val


# ============================================================
# 静态页面
# ============================================================

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
