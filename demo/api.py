"""学生成绩 Demo 的 FastAPI 路由。"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from demo import registry
from nl_batch import handle_batch_query
from nl_graph import handle_graph_query
from nl_oag import get_conversation, handle_oag_query, list_conversations
from ontology_engine.action import execute_action
from ontology_engine.database import get_connection
from ontology_engine.functions import call_function, compute_derived_property
from ontology_engine.query import (
    aggregate_objects,
    get_object,
    query_object_set,
    query_objects,
    traverse_link,
)

router = APIRouter(prefix="/ontology")


class AggregateRequest(BaseModel):
    aggregations: list[dict]
    filters: Optional[dict] = None
    group_by: Optional[list[str]] = None
    order_by: Optional[str] = None
    order_dir: str = "desc"
    limit: int = 50


class ActionRequest(BaseModel):
    params: dict


@router.get("/schema")
def get_schema():
    """返回完整 Ontology Schema，供前端图谱渲染和 LLM Tool Definition 使用。"""
    objects = {}
    for name, object_def in registry.OBJECT_TYPES.items():
        objects[name] = {
            "apiName": object_def.api_name,
            "displayName": object_def.display_name,
            "table": object_def.table,
            "properties": [
                {"name": prop.name, "type": prop.prop_type, "dataType": prop.data_type}
                for prop in object_def.properties
            ],
        }

    links = {}
    for name, link_def in registry.LINK_TYPES.items():
        links[name] = {
            "apiName": link_def.api_name,
            "displayName": link_def.display_name,
            "sourceType": link_def.source_type,
            "targetType": link_def.target_type,
            "cardinality": link_def.cardinality,
            "reverseName": link_def.reverse_name,
        }

    actions = {}
    for name, action_def in registry.ACTION_TYPES.items():
        actions[name] = {
            "apiName": action_def.api_name,
            "displayName": action_def.display_name,
            "actionType": action_def.action_type,
            "boundObject": action_def.bound_object,
            "params": [
                {"name": param.name, "type": param.param_type, "required": param.required}
                for param in action_def.params
            ],
        }

    functions = {}
    for name, function_def in registry.FUNCTIONS.items():
        functions[name] = {
            "apiName": function_def.api_name,
            "displayName": function_def.display_name,
            "funcType": function_def.func_type,
            "boundObject": function_def.bound_object,
            "returnType": function_def.return_type,
            "params": [
                {"name": param.name, "type": param.param_type, "required": param.required}
                for param in function_def.params
            ],
        }

    return {"objects": objects, "links": links, "actions": actions, "functions": functions}


@router.get("/objects/{object_type}")
def api_query_objects(
    object_type: str,
    name: Optional[str] = Query(None),
    order_by: Optional[str] = Query(None),
    order_dir: str = Query("asc"),
    limit: int = Query(50),
    offset: int = Query(0),
):
    """查询对象列表，支持 name 模糊匹配。"""
    where = {"name": name} if name else None
    results = query_objects(
        object_type,
        where=where,
        order_by=order_by,
        order_dir=order_dir,
        limit=limit,
        offset=offset,
    )
    for obj in results:
        _fill_derived(object_type, obj)
    return {"data": results, "count": len(results)}


@router.get("/objects/{object_type}/{object_id}")
def api_get_object(object_type: str, object_id: str):
    """获取单个对象，含派生属性。"""
    obj = get_object(object_type, object_id)
    if obj is None:
        raise HTTPException(404, f"{object_type} object_id={object_id} not found")
    _fill_derived(object_type, obj)
    return obj


@router.get("/objects/{object_type}/{object_id}/links/{link_name}")
def api_traverse_link(object_type: str, object_id: str, link_name: str):
    """沿 Link 遍历获取关联对象。"""
    results = traverse_link(object_type, object_id, link_name)
    return {"data": results, "count": len(results)}


@router.post("/objects/{object_type}/aggregate")
def api_aggregate_objects(object_type: str, req: AggregateRequest):
    """通用聚合查询：支持 count/sum/avg/min/max/count_distinct + 跨 Link 分组。"""
    return aggregate_objects(
        object_type,
        aggregations=req.aggregations,
        filters=req.filters,
        group_by=req.group_by,
        order_by=req.order_by,
        order_dir=req.order_dir,
        limit=req.limit,
    )


@router.get("/functions/{func_name}")
def api_call_function(func_name: str, request: Request):
    """调用 Function，动态接收所有 query 参数。"""
    params = {}
    for key, value in request.query_params.items():
        if value.isdigit():
            params[key] = int(value)
        elif value.replace(".", "", 1).replace("-", "", 1).isdigit():
            params[key] = float(value)
        else:
            params[key] = value
    return call_function(func_name, params)


@router.post("/actions/{action_name}")
def api_execute_action(action_name: str, req: ActionRequest):
    """执行 Action。"""
    result = execute_action(action_name, req.params)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "Action failed"))
    return result


@router.get("/object-sets")
def api_list_object_sets():
    """列出所有 ObjectSet 定义。"""
    result = {}
    for name, object_set_def in registry.OBJECT_SETS.items():
        mode = "filters" if object_set_def.filters else "sql"
        result[name] = {
            "apiName": object_set_def.api_name,
            "displayName": object_set_def.display_name,
            "objectType": object_set_def.object_type,
            "description": object_set_def.description,
            "definitionMode": mode,
            "filters": object_set_def.filters if object_set_def.filters else None,
        }
    return result


@router.get("/object-sets/{set_name}")
def api_query_object_set(set_name: str, limit: int = Query(50)):
    """查询 ObjectSet 中的对象。"""
    result = query_object_set(set_name, limit=limit)
    if not result.get("success"):
        raise HTTPException(404, result.get("error", "ObjectSet not found"))
    return result


@router.get("/tables")
def api_list_tables():
    """返回所有原始数据表的结构和数据。"""
    tables = {}
    for table_name in ["student", "teacher", "course", "tc", "score", "audit_log"]:
        conn = get_connection()
        cols = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        columns = [{"name": col["name"], "type": col["type"], "pk": bool(col["pk"])} for col in cols]
        rows = conn.execute(f"SELECT * FROM {table_name} LIMIT 100").fetchall()
        conn.close()
        tables[table_name] = {
            "columns": columns,
            "data": [dict(row) for row in rows],
            "row_count": len(rows),
        }
    return {"success": True, "tables": tables}


@router.post("/nl-query")
async def api_nl_query(req: dict):
    """Batch Plan 模式：LLM 输出完整 JSON 操作序列，引擎逐条执行。"""
    return await handle_batch_query(req.get("query", ""))


@router.post("/nl-query-graph")
async def api_nl_query_graph(req: dict):
    """Graph Walk 模式：LLM 通过工具在内存实例图谱上逐步游走探索。"""
    return await handle_graph_query(
        req.get("query", ""),
        max_iterations=req.get("max_iterations", 20),
    )


@router.post("/nl-query-oag")
async def api_nl_query_oag(req: dict):
    """OAG 模式：LLM 在对象类型层操作，引擎负责 Link JOIN 编译和派生属性自动计算。"""
    return await handle_oag_query(
        req.get("query", ""),
        max_iterations=req.get("max_iterations", 20),
    )


@router.get("/conversations")
def api_list_conversations(limit: int = 50):
    """返回最近 N 条 OAG 对话摘要列表。"""
    return {"success": True, "data": list_conversations(limit)}


@router.get("/conversations/{conv_id}")
def api_get_conversation(conv_id: str):
    """按 id 返回完整对话记录。"""
    data = get_conversation(conv_id)
    if data is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return {"success": True, "data": data}


@router.get("/graph")
def api_graph_data():
    """返回全量图谱数据：节点（所有 Object）+ 边（所有 Link）。"""
    nodes = []
    edges = []

    for object_name, object_def in registry.OBJECT_TYPES.items():
        pk_prop = next((prop for prop in object_def.properties if prop.prop_type == "primary_key"), None)
        if not pk_prop:
            continue

        conn = get_connection()
        rows = conn.execute(f"SELECT * FROM {object_def.table}").fetchall()
        conn.close()

        for row in rows:
            object_id = row[pk_prop.column]
            label_name = row["name"] if "name" in row.keys() else f"{object_name}#{object_id}"
            title_lines = [
                f"<b>{object_def.display_name} ({object_name})</b>",
                f"{pk_prop.name}: {object_id}",
            ]
            for prop in object_def.properties:
                if prop.prop_type == "derived":
                    continue
                if prop.column in row.keys() and prop.name != pk_prop.name:
                    title_lines.append(f"{prop.name}: {row[prop.column]}")
            nodes.append({
                "id": f"{object_name}-{object_id}",
                "objectType": object_name,
                "objectId": object_id,
                "label": f"{label_name}\n{object_id}",
                "title": "<br>".join(title_lines),
                "group": object_name,
            })

    for link_def in registry.LINK_TYPES.values():
        source_def = registry.OBJECT_TYPES[link_def.source_type]
        source_pk = link_def.source_pk or next(
            prop.column for prop in source_def.properties if prop.prop_type == "primary_key"
        )
        conn = get_connection()
        if link_def.cardinality == "many_to_many":
            rows = conn.execute(
                f"SELECT {link_def.bridge_source_fk}, {link_def.bridge_target_fk} FROM {link_def.bridge_table}"
            ).fetchall()
        else:
            rows = conn.execute(f"SELECT {source_pk}, {link_def.source_fk} FROM {source_def.table}").fetchall()
        conn.close()

        for row in rows:
            if link_def.cardinality == "many_to_many":
                source_id = row[link_def.bridge_source_fk]
                target_id = row[link_def.bridge_target_fk]
            else:
                source_id = row[source_pk]
                target_id = row[link_def.source_fk]
            if target_id:
                edges.append({
                    "from": f"{link_def.source_type}-{source_id}",
                    "to": f"{link_def.target_type}-{target_id}",
                    "label": link_def.api_name,
                    "displayLabel": link_def.display_name,
                    "title": f"{link_def.display_name} ({link_def.cardinality})",
                })

    return {"nodes": nodes, "edges": edges}


@router.get("/graph/schema")
def api_schema_graph():
    """返回 Ontology 类型层图谱：Object Type 为节点，Link Type 为边。"""
    nodes = []
    edges = []

    for name, object_def in registry.OBJECT_TYPES.items():
        props_summary = "<br>".join(
            f"{prop.name} [{prop.prop_type}] ({prop.data_type})" for prop in object_def.properties
        )
        pk_prop = next((prop for prop in object_def.properties if prop.prop_type == "primary_key"), None)
        nodes.append({
            "id": f"Type-{name}",
            "label": f"{object_def.display_name}\n{name}",
            "group": name,
            "title": f"<b>{object_def.display_name} ({name})</b><br>"
                     f"表: {object_def.table}<br>"
                     f"主键: {pk_prop.name if pk_prop else '-'}<br>"
                     f"属性:<br>{props_summary}",
            "shape": "box",
            "size": 35,
            "font": {"size": 14, "color": "#333", "multi": True},
            "borderWidth": 2,
            "level": 0,
        })

    for name, link_def in registry.LINK_TYPES.items():
        edge_detail = (
            f"桥表: {link_def.bridge_table} ({link_def.bridge_source_fk}, {link_def.bridge_target_fk})"
            if link_def.cardinality == "many_to_many"
            else f"外键: {link_def.source_type}.{link_def.source_fk} -> {link_def.target_type}.{link_def.target_pk or 'PK'}"
        )
        edges.append({
            "from": f"Type-{link_def.source_type}",
            "to": f"Type-{link_def.target_type}",
            "label": f"{link_def.display_name}\n({link_def.api_name})\n[{link_def.cardinality}]",
            "title": (
                f"<b>{link_def.display_name} ({link_def.api_name})</b><br>"
                f"{link_def.source_type} -> {link_def.target_type}<br>"
                f"关系: {link_def.cardinality}<br>"
                f"{edge_detail}"
            ),
            "arrows": "to",
            "font": {"size": 11, "color": "#555", "background": "white", "multi": True},
            "width": 2,
            "color": {"color": "#888", "opacity": 0.8},
        })

    for name, interface_def in registry.INTERFACES.items():
        nodes.append({
            "id": f"Interface-{name}",
            "label": f"◆ {interface_def.display_name}\n{name}",
            "group": "Interface",
            "title": f"<b>{interface_def.display_name} ({name})</b><br>"
                     f"{interface_def.description}<br>"
                     f"共享属性: {', '.join(interface_def.shared_properties) if interface_def.shared_properties else '无'}<br>"
                     f"共享Function: {', '.join(interface_def.shared_functions)}<br>"
                     f"实现者: {', '.join(interface_def.implementors)}",
            "shape": "diamond",
            "size": 30,
            "color": {"background": "#f9f0ff", "border": "#722ed1"},
            "font": {"size": 12, "color": "#531dab", "multi": True},
            "borderWidth": 2,
            "level": 1,
        })
        for implementor in interface_def.implementors:
            edges.append({
                "from": f"Interface-{name}",
                "to": f"Type-{implementor}",
                "label": "implements",
                "arrows": "to",
                "dashes": [8, 4],
                "font": {"size": 9, "color": "#999", "background": "white"},
                "width": 1,
                "color": {"color": "#b37feb", "opacity": 0.6},
            })

    return {"nodes": nodes, "edges": edges}


@router.get("/interfaces")
def api_interfaces():
    """返回所有 Interface 定义。"""
    result = {}
    for name, interface_def in registry.INTERFACES.items():
        result[name] = {
            "apiName": interface_def.api_name,
            "displayName": interface_def.display_name,
            "description": interface_def.description,
            "sharedProperties": interface_def.shared_properties,
            "sharedFunctions": interface_def.shared_functions,
            "implementors": interface_def.implementors,
        }
    return result


def _fill_derived(object_type: str, obj: dict) -> None:
    object_def = registry.OBJECT_TYPES.get(object_type)
    if not object_def:
        return
    pk_prop = next((prop for prop in object_def.properties if prop.prop_type == "primary_key"), None)
    obj_id = obj.get(pk_prop.name) if pk_prop else None
    if obj_id is None:
        return
    for prop in object_def.properties:
        if prop.prop_type == "derived":
            obj[prop.name] = compute_derived_property(object_type, obj_id, prop.name)
