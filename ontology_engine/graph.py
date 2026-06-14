"""
内存图谱引擎 — 邻接表结构的对象关系图，支持 O(1) 邻接遍历。

LLM 通过图原生工具在图上游走，每次探索后系统返回「从当前节点能去哪儿」的元数据。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from ontology_engine.database import get_connection
from ontology_engine.registry import OBJECT_TYPES, LINK_TYPES, FUNCTIONS, ACTION_TYPES, INTERFACES


@dataclass
class GraphTraversal:
    """从节点可执行的一条遍历路径"""
    name: str           # 传给 traverse() 的名称，如 "scores"
    display_name: str   # 给 LLM 看的，如 "成绩"
    target_type: str    # 目标 Object Type
    direction: str      # "forward" | "reverse"


@dataclass
class NodeMetadata:
    """某 Object Type 的静态元数据（建图时预计算，不随实例变化）"""
    traversals: list = field(default_factory=list)
    bound_functions: list = field(default_factory=list)
    available_actions: list = field(default_factory=list)


class OntologyGraph:
    """内存图谱 — 邻接表结构"""

    def __init__(self):
        self._nodes: dict[str, dict] = {}            # node_key → {properties}
        self._node_types: dict[str, str] = {}         # node_key → object_type
        self._adj_out: dict[str, dict[str, list[str]]] = {}  # node_key → {traversal_name: [target_node_keys]}
        self._metadata: dict[str, NodeMetadata] = {}  # object_type → NodeMetadata
        self._loaded = False

    # ---- 加载 ----

    def load_from_db(self):
        """从 SQLite 全量加载到内存图"""
        conn = get_connection()
        try:
            # 1. 加载所有对象节点
            for type_name, obj_def in OBJECT_TYPES.items():
                pk_prop = next((p for p in obj_def.properties if p.prop_type == "primary_key"), None)
                if not pk_prop:
                    continue
                regular_props = [(p.name, p.column) for p in obj_def.properties
                                 if p.prop_type != "derived" and p.column]
                if not regular_props:
                    continue
                col_names = [c for _, c in regular_props]
                cols_str = ", ".join(col_names)
                rows = conn.execute(f"SELECT {cols_str} FROM {obj_def.table}").fetchall()
                for row in rows:
                    object_id = row[pk_prop.column]
                    node_key = f"{type_name}-{object_id}"
                    # 用属性名（非列名）存储
                    props = {}
                    for prop_name, col_name in regular_props:
                        props[prop_name] = row[col_name]
                    # 统一加 name 显示名（Score 没有 name 列）
                    if "name" not in props:
                        props["name"] = f"{obj_def.display_name}#{object_id}"
                    self._nodes[node_key] = props
                    self._node_types[node_key] = type_name
                    self._adj_out[node_key] = {}

            # 2. 构建邻接边
            for link_name, link_def in LINK_TYPES.items():
                source_def = OBJECT_TYPES[link_def.source_type]
                source_pk = next(
                    p.column for p in source_def.properties if p.prop_type == "primary_key"
                )
                rows = conn.execute(
                    f"SELECT {source_pk}, {link_def.source_fk} FROM {source_def.table}"
                ).fetchall()
                for row in rows:
                    source_key = f"{link_def.source_type}-{row[source_pk]}"
                    target_id = row[link_def.source_fk]
                    if target_id is None:
                        continue
                    target_key = f"{link_def.target_type}-{target_id}"
                    if target_key not in self._nodes:
                        continue
                    self._adj_out.setdefault(source_key, {}).setdefault(
                        link_def.api_name, []).append(target_key)
                    self._adj_out.setdefault(target_key, {}).setdefault(
                        link_def.reverse_name, []).append(source_key)
        finally:
            conn.close()

        # 3. 预计算 NodeMetadata
        self._build_all_metadata()
        self._loaded = True

    def _build_all_metadata(self):
        for type_name in OBJECT_TYPES:
            self._metadata[type_name] = self._compute_metadata(type_name)

    def _compute_metadata(self, obj_type: str) -> NodeMetadata:
        """计算某 Object Type 的静态元数据：能走哪些边、有哪些函数/操作"""
        meta = NodeMetadata()

        # 遍历路径
        for link in LINK_TYPES.values():
            if link.source_type == obj_type:
                meta.traversals.append(GraphTraversal(
                    name=link.api_name,
                    display_name=link.display_name,
                    target_type=link.target_type,
                    direction="forward",
                ))
            if link.target_type == obj_type:
                meta.traversals.append(GraphTraversal(
                    name=link.reverse_name,
                    display_name=f"反向{link.display_name}",
                    target_type=link.source_type,
                    direction="reverse",
                ))

        # 绑定函数
        for fname, fdef in FUNCTIONS.items():
            if fdef.bound_object == obj_type or fdef.bound_object == "Nameable" or fdef.bound_object == "Scoreable":
                # 检查 Interface 实现
                if fdef.bound_object in ("Nameable", "Scoreable"):
                    for iface in INTERFACES.values():
                        if iface.api_name == fdef.bound_object and obj_type in iface.implementors:
                            meta.bound_functions.append({
                                "name": fname,
                                "display_name": fdef.display_name,
                                "return_type": fdef.return_type,
                                "params": [{"name": p.name, "type": p.param_type, "required": p.required}
                                           for p in fdef.params],
                            })
                            break
                else:
                    meta.bound_functions.append({
                        "name": fname,
                        "display_name": fdef.display_name,
                        "return_type": fdef.return_type,
                        "params": [{"name": p.name, "type": p.param_type, "required": p.required}
                                   for p in fdef.params],
                    })

        # 绑定操作
        for aname, adef in ACTION_TYPES.items():
            if adef.bound_object == obj_type:
                meta.available_actions.append({
                    "name": aname,
                    "display_name": adef.display_name,
                    "params": [{"name": p.name, "type": p.param_type, "required": p.required}
                               for p in adef.params],
                })

        return meta

    # ---- 查询 ----

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def search_objects(self, object_type: str, filters: dict = None,
                       fuzzy: bool = False) -> list[dict]:
        """按类型 + 属性过滤搜索。fuzzy=True 时字符串值做子串匹配（大小写不敏感）。"""
        results = []
        for node_key, props in self._nodes.items():
            if self._node_types[node_key] != object_type:
                continue
            if filters:
                match = True
                for k, v in filters.items():
                    prop_val = str(props.get(k, ""))
                    if fuzzy and isinstance(v, str):
                        if v.lower() not in prop_val.lower():
                            match = False
                            break
                    elif prop_val != str(v):
                        match = False
                        break
                if not match:
                    continue
            results.append(self._enrich(node_key, props))
        return results

    def search_by_semantic(self, keyword: str,
                           object_types: list[str] = None) -> list[dict]:
        """跨类型模糊搜索。在所有字符串属性中做子串匹配（大小写不敏感）。
        object_types 可限定搜索范围，默认搜索全部类型。"""
        results = []
        target_types = set(object_types) if object_types else set(OBJECT_TYPES.keys())
        for node_key, props in self._nodes.items():
            obj_type = self._node_types[node_key]
            if obj_type not in target_types:
                continue
            for k, v in props.items():
                if isinstance(v, str) and keyword.lower() in v.lower():
                    results.append(self._enrich(node_key, props))
                    break
        return results

    def list_object_types(self) -> list[dict]:
        """返回所有已注册 Object Type 及其元数据（属性、遍历、函数、操作、实例数）。"""
        result = []
        for type_name, obj_def in OBJECT_TYPES.items():
            meta = self._metadata.get(type_name)
            info = {
                "object_type": type_name,
                "display_name": obj_def.display_name,
                "properties": [
                    {"name": p.name, "data_type": p.data_type, "type": p.prop_type}
                    for p in obj_def.properties
                ],
                "count": sum(1 for nt in self._node_types.values() if nt == type_name),
            }
            if meta:
                info["traversals"] = [
                    {"name": t.name, "display_name": t.display_name,
                     "target_type": t.target_type}
                    for t in meta.traversals
                ]
                info["functions"] = [
                    {"name": f["name"], "display_name": f["display_name"]}
                    for f in meta.bound_functions
                ]
                info["actions"] = [
                    {"name": a["name"], "display_name": a["display_name"]}
                    for a in meta.available_actions
                ]
            result.append(info)
        return result

    def get_node(self, node_key: str) -> dict | None:
        """O(1) 节点查找"""
        props = self._nodes.get(node_key)
        if props is None:
            return None
        return self._enrich(node_key, props)

    def traverse(self, node_key: str, traversal_name: str) -> list[dict]:
        """沿指定边遍历到邻居节点"""
        neighbors = self._adj_out.get(node_key, {}).get(traversal_name, [])
        results = []
        for nk in neighbors:
            results.append(self._enrich(nk, self._nodes[nk]))
        return results

    def get_node_metadata(self, object_type: str) -> NodeMetadata:
        return self._metadata.get(object_type)

    def get_available_traversals(self, node_key: str) -> list[str]:
        """返回某节点当前可用的遍历名（动态，可能因节点不同而变化）"""
        return list(self._adj_out.get(node_key, {}).keys())

    # ---- 内部 ----

    def _enrich(self, node_key: str, props: dict) -> dict:
        """给节点附加元数据：node_key、objectType、可用遍历、可用函数"""
        obj_type = self._node_types[node_key]
        enriched = dict(props)
        enriched["_node_key"] = node_key
        enriched["_objectType"] = obj_type

        meta = self._metadata.get(obj_type)
        if meta:
            enriched["_traversals"] = [
                {"name": t.name, "display_name": t.display_name,
                 "target_type": t.target_type, "direction": t.direction}
                for t in meta.traversals
            ]
            enriched["_functions"] = meta.bound_functions
            enriched["_actions"] = meta.available_actions
        else:
            enriched["_traversals"] = []
            enriched["_functions"] = []
            enriched["_actions"] = []

        # 动态出边列表（实际存在邻居的边才列出）
        available = self._adj_out.get(node_key, {})
        enriched["_available_traversals"] = [
            name for name, targets in available.items() if targets
        ]

        # 为 Score 节点附加关联对象名，避免 LLM 逐个 traverse
        if obj_type == "Score":
            ctx = []
            for edge_name in ("earnedBy", "forCourse"):
                targets = available.get(edge_name, [])
                if targets:
                    target_node = self._nodes.get(targets[0], {})
                    target_name = target_node.get("name", targets[0])
                    ctx.append(target_name)
            if ctx:
                enriched["_context"] = " → ".join(ctx)

        # 自动计算派生属性（avgScore, passRate 等）
        obj_def = OBJECT_TYPES.get(obj_type)
        if obj_def:
            pk_prop = next((p for p in obj_def.properties if p.prop_type == "primary_key"), None)
            obj_id = props.get(pk_prop.name) if pk_prop else None
            if obj_id:
                from ontology_engine.functions import compute_derived_property
                for p in obj_def.properties:
                    if p.prop_type == "derived" and p.name not in enriched:
                        val = compute_derived_property(obj_type, obj_id, p.name)
                        enriched[p.name] = val

        return enriched


# ---- 单例 ----

_graph_instance: OntologyGraph | None = None


def get_graph() -> OntologyGraph:
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = OntologyGraph()
        _graph_instance.load_from_db()
    return _graph_instance


def reload_graph():
    """数据变更后重新加载图谱"""
    global _graph_instance
    _graph_instance = OntologyGraph()
    _graph_instance.load_from_db()
