"""
查询引擎 — 将 Ontology 语义操作（查 Object、遍历 Link）翻译为 SQL。
这是「语义表示层用 Ontology，计算层用 SQL」的核心体现。
"""

from typing import Optional
from ontology_engine.database import get_connection
from ontology_engine.registry import OBJECT_TYPES, LINK_TYPES


# ============================================================
# 条件编译器 — 支持多运算符
# ============================================================

# 简单二元运算符映射
_OP_MAP = {
    "eq": "=", "ne": "!=",
    "gt": ">", "gte": ">=",
    "lt": "<", "lte": "<=",
    "like": "LIKE", "ilike": "LIKE",
}


def _compile_condition(col_ref: str, value, params: list) -> str:
    """将 (列引用, 值) 编译为 SQL 条件片段，追加参数到 params。

    支持格式：
    - 标量值                              → col = ?
    - {"op":"gt",  "value":85}           → col > ?
    - {"op":"gte", "value":85}           → col >= ?
    - {"op":"lt",  "value":90}           → col < ?
    - {"op":"lte", "value":90}           → col <= ?
    - {"op":"ne",  "value":0}            → col != ?
    - {"op":"between","value":[80,90]}   → col BETWEEN ? AND ?
    - {"op":"in",   "value":["a","b"]}   → col IN (?,?)
    - {"op":"not_in","value":[...]}      → col NOT IN (?,?)
    - {"op":"like", "value":"%张%"}      → col LIKE ?
    - {"op":"is_null"}                   → col IS NULL
    - {"op":"is_not_null"}               → col IS NOT NULL
    """
    if not (isinstance(value, dict) and "op" in value):
        params.append(value)
        return f"{col_ref} = ?"

    op = value["op"].lower()
    v = value.get("value")

    if op == "is_null":
        return f"{col_ref} IS NULL"
    if op == "is_not_null":
        return f"{col_ref} IS NOT NULL"
    if op == "between":
        if not (isinstance(v, (list, tuple)) and len(v) == 2):
            raise ValueError(f"'between' 需要长度为 2 的列表，收到: {v!r}")
        params.extend(v)
        return f"{col_ref} BETWEEN ? AND ?"
    if op in ("in", "not_in"):
        if not isinstance(v, (list, tuple)) or len(v) == 0:
            raise ValueError(f"'{op}' 需要非空列表，收到: {v!r}")
        placeholders = ",".join("?" * len(v))
        params.extend(v)
        sql_op = "IN" if op == "in" else "NOT IN"
        return f"{col_ref} {sql_op} ({placeholders})"
    if op in _OP_MAP:
        if v is None:
            raise ValueError(f"运算符 '{op}' 需要提供 'value'")
        params.append(v)
        return f"{col_ref} {_OP_MAP[op]} ?"
    raise ValueError(
        f"不支持的运算符 '{op}'，可用: "
        f"{list(_OP_MAP.keys()) + ['between', 'in', 'not_in', 'is_null', 'is_not_null']}"
    )


def get_object(object_type: str, object_id: int) -> Optional[dict]:
    """获取单个对象（含派生属性）"""
    obj_def = OBJECT_TYPES[object_type]
    regular_cols = [p.column for p in obj_def.properties if p.prop_type in ("primary_key", "regular")]
    cols_str = ", ".join(regular_cols)

    conn = get_connection()
    row = conn.execute(
        f"SELECT {cols_str} FROM {obj_def.table} WHERE id = ?",
        (object_id,)
    ).fetchone()
    conn.close()

    if row is None:
        return None

    result = {"_objectType": object_type, "_id": object_id}
    for p in obj_def.properties:
        if p.prop_type == "derived":
            result[p.name] = None  # 由 caller 按需计算
        elif p.column in row.keys():
            result[p.name] = row[p.column]

    return result


def query_objects(object_type: str, where: Optional[dict] = None,
                  order_by: Optional[str] = None, order_dir: str = "asc",
                  limit: int = 50, offset: int = 0) -> list[dict]:
    """查询对象列表"""
    obj_def = OBJECT_TYPES[object_type]
    regular_cols = [p.column for p in obj_def.properties if p.prop_type in ("primary_key", "regular")]
    cols_str = ", ".join(regular_cols)

    sql = f"SELECT {cols_str} FROM {obj_def.table}"
    params = []

    if where:
        conditions = []
        for key, val in where.items():
            prop = next((p for p in obj_def.properties if p.name == key), None)
            col = prop.column if prop else key
            conditions.append(f"{col} = ?")
            params.append(val)
        sql += " WHERE " + " AND ".join(conditions)

    if order_by:
        prop = next((p for p in obj_def.properties if p.name == order_by), None)
        col = prop.column if prop else order_by
        direction = "DESC" if order_dir.lower() == "desc" else "ASC"
        sql += f" ORDER BY {col} {direction}"

    sql += f" LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for row in rows:
        obj = {"_objectType": object_type}
        for p in obj_def.properties:
            if p.prop_type != "derived" and p.column in row.keys():
                obj[p.name] = row[p.column]
            elif p.prop_type == "derived":
                obj[p.name] = None
        results.append(obj)
    return results


def traverse_link(object_type: str, object_id: int, link_name: str) -> list[dict]:
    """沿 Link 遍历到关联对象。

    支持正向和反向遍历：
    - 正向：从持有 FK 的源对象遍历到目标对象
    - 反向：从目标对象反查到所有引用它的源对象
    """
    # 正向遍历：当前对象是 Link 的 source（持有 FK）
    link = LINK_TYPES.get(link_name)
    if link and link.source_type == object_type:
        source_def = OBJECT_TYPES[link.source_type]
        target_def = OBJECT_TYPES[link.target_type]
        target_cols = [p.column for p in target_def.properties
                       if p.prop_type in ("primary_key", "regular")]
        cols_str = ", ".join(f"t.{c}" for c in target_cols)

        sql = f"""
            SELECT {cols_str}
            FROM {target_def.table} t
            JOIN {source_def.table} s ON s.{link.source_fk} = t.id
            WHERE s.id = ?
        """
        conn = get_connection()
        rows = conn.execute(sql, (object_id,)).fetchall()
        conn.close()

        return [_row_to_dict(row, target_def) for row in rows]

    # 反向遍历：当前对象是 Link 的 target（被 FK 引用）
    rev_link = next((l for l in LINK_TYPES.values()
                     if l.target_type == object_type and l.reverse_name == link_name), None)
    if rev_link:
        source_def = OBJECT_TYPES[rev_link.source_type]
        source_cols = [p.column for p in source_def.properties
                       if p.prop_type in ("primary_key", "regular")]
        cols_str = ", ".join(f"s.{c}" for c in source_cols)

        sql = f"""
            SELECT {cols_str}
            FROM {source_def.table} s
            WHERE s.{rev_link.source_fk} = ?
        """
        conn = get_connection()
        rows = conn.execute(sql, (object_id,)).fetchall()
        conn.close()

        return [_row_to_dict(row, source_def) for row in rows]

    return []


def _row_to_dict(row, obj_def) -> dict:
    result = {"_objectType": obj_def.api_name}
    for p in obj_def.properties:
        if p.prop_type != "derived" and p.column in row.keys():
            result[p.name] = row[p.column]
        elif p.prop_type == "derived":
            result[p.name] = None
    return result


# ============================================================
# OAG 查询引擎 — 跨 Link 查询（类型层查询，引擎编译 JOIN）
# ============================================================


def _find_link_by_segment(current_type: str, segment: str):
    """给定当前类型和一个路径段，找到对应的 LinkTypeDef。

    两种解析策略：
    1. 正向：segment 匹配某个 forward link 的 target_type（如 Score → student）
    2. 反向：segment 匹配某个反向 link 的 reverse_name（如 Student → scores）

    Returns (LinkTypeDef, "forward"|"reverse") or (None, None).
    """
    # 正向：segment 等于目标类型名（大小写不敏感）
    for link in LINK_TYPES.values():
        if link.source_type == current_type and link.target_type.lower() == segment.lower():
            return link, "forward"

    # 反向：segment 等于某个 Link 的 reverse_name
    for link in LINK_TYPES.values():
        if link.target_type == current_type and link.reverse_name.lower() == segment.lower():
            return link, "reverse"

    return None, None


def _build_link_joins(
    query_type: str, link_filters: dict, fuzzy: bool = False,
    join_clauses: Optional[list] = None,
    join_cache: Optional[dict] = None,
    alias_counter: Optional[list] = None,
) -> tuple[list[str], list[str], list]:
    """根据点号过滤器构建 SQL JOIN 链。

    对 filter key "course.teacher.name"：
    1. 拆分为路径段 ["course", "teacher"]，最终属性 "name"
    2. 逐段解析 LinkTypeDef，添加 JOIN 子句
    3. 在最终表上添加 WHERE 条件

    去重：相同路径前缀共享同一个 JOIN（如 student.name + student.className）。

    支持运算符：value 可以是标量或 {"op":"gt","value":85} 等格式。

    join_clauses / join_cache / alias_counter 可由外部传入，实现跨调用共享 JOIN 状态
    （用于同时处理过滤和跨 Link ORDER BY 的场景）。

    Returns (join_clauses, where_clauses, params).
    """
    if join_clauses is None:
        join_clauses = []
    if join_cache is None:
        join_cache = {}
    if alias_counter is None:
        alias_counter = [1]

    where_clauses = []
    params = []

    for key, value in link_filters.items():
        parts = key.split(".")
        prop_name = parts[-1]
        path_segments = parts[:-1]

        current_type = query_type
        current_alias = "t0"

        for segment in path_segments:
            cache_key = (current_alias, segment)
            if cache_key in join_cache:
                current_alias = join_cache[cache_key]
                # 更新 current_type
                link, _ = _find_link_by_segment(current_type, segment)
                if link:
                    current_type = (
                        link.target_type
                        if link.source_type == current_type
                        else link.source_type
                    )
                continue

            link, direction = _find_link_by_segment(current_type, segment)
            if link is None:
                # 列出可用路径做错误提示
                available = []
                for l in LINK_TYPES.values():
                    if l.source_type == current_type:
                        available.append(f"{l.target_type}(正向)")
                    if l.target_type == current_type:
                        available.append(f"{l.reverse_name}(反向→{l.source_type})")
                raise ValueError(
                    f"无法从 '{current_type}' 解析路径段 '{segment}'。"
                    f"可用: {', '.join(available) if available else '无'}"
                )

            new_alias = f"l{alias_counter[0]}"
            alias_counter[0] += 1

            if direction == "forward":
                target_table = OBJECT_TYPES[link.target_type].table
                join_clauses.append(
                    f"JOIN {target_table} {new_alias} "
                    f"ON {current_alias}.{link.source_fk} = {new_alias}.id"
                )
                current_type = link.target_type
            else:  # reverse
                source_table = OBJECT_TYPES[link.source_type].table
                join_clauses.append(
                    f"JOIN {source_table} {new_alias} "
                    f"ON {current_alias}.id = {new_alias}.{link.source_fk}"
                )
                current_type = link.source_type

            join_cache[cache_key] = new_alias
            current_alias = new_alias

        # current_alias 现在指向包含 prop_name 的表
        target_obj_def = OBJECT_TYPES[current_type]
        prop = next(
            (p for p in target_obj_def.properties if p.name == prop_name), None
        )
        if not prop:
            raise ValueError(
                f"属性 '{prop_name}' 在类型 '{current_type}' 中不存在。"
                f"可用: {[p.name for p in target_obj_def.properties]}"
            )

        col_ref = f"{current_alias}.{prop.column}"

        # fuzzy 仅对 TEXT 标量值（非运算符 dict）有效
        if fuzzy and prop.data_type == "TEXT" and not isinstance(value, dict):
            where_clauses.append(f"{col_ref} LIKE ?")
            params.append(f"%{value}%")
        else:
            where_clauses.append(_compile_condition(col_ref, value, params))

    return join_clauses, where_clauses, params


def fill_derived_batch(results: list[dict], object_type: str):
    """批量为查询结果填充派生属性。"""
    from ontology_engine.functions import compute_derived_property

    obj_def = OBJECT_TYPES.get(object_type)
    if not obj_def:
        return
    for obj in results:
        obj_id = obj.get("id")
        if obj_id is None:
            continue
        for p in obj_def.properties:
            if p.prop_type == "derived":
                val = compute_derived_property(object_type, obj_id, p.name)
                obj[p.name] = val


def query_objects_v2(
    object_type: str,
    filters: Optional[dict] = None,
    fuzzy: bool = False,
    order_by: Optional[str] = None,
    order_dir: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """跨 Link 查询对象，支持点号链式过滤、多运算符、OR 条件。

    filter 格式（所有格式可混用）：
    - 等值:   {"name": "张三"}
    - 运算符: {"scoreValue": {"op": "gte", "value": 85}}
             {"scoreValue": {"op": "between", "value": [80, 90]}}
             {"name": {"op": "in", "value": ["张三", "李四"]}}
             {"field": {"op": "is_null"}}
    - 跨Link: {"student.name": "张三", "course.name": "数学"}
    - 跨Link运算符: {"score.scoreValue": {"op": "gt", "value": 60}}
    - OR 条件: {"$or": [{"name": "张三"}, {"className": "理学院"}]}
              （$or 内支持直接属性及运算符，不支持跨 Link）

    order_by 支持点号跨 Link 排序，如 "course.name"。
    当存在 JOIN 时自动加 DISTINCT 防止行膨胀。
    """
    obj_def = OBJECT_TYPES.get(object_type)
    if not obj_def:
        raise ValueError(f"Unknown object type: {object_type}")

    # 共享 JOIN 状态（过滤与 ORDER BY 共用，避免重复 JOIN）
    join_clauses: list[str] = []
    join_cache: dict = {}
    alias_counter = [1]

    # 拆分 filters：$or / 跨Link / 直接属性
    filters = dict(filters) if filters else {}
    or_groups = filters.pop("$or", None)

    direct_filters = {}
    link_filters = {}
    for key, value in filters.items():
        if "." in key:
            link_filters[key] = value
        else:
            direct_filters[key] = value

    regular_cols = [
        p.column
        for p in obj_def.properties
        if p.prop_type in ("primary_key", "regular")
    ]
    cols_str = ", ".join(f"t0.{c}" for c in regular_cols)
    params: list = []
    where_clauses: list[str] = []

    # 跨 Link 过滤 → JOIN + WHERE（共享 join_cache）
    if link_filters:
        _, link_where, link_params = _build_link_joins(
            object_type, link_filters, fuzzy,
            join_clauses, join_cache, alias_counter,
        )
        where_clauses.extend(link_where)
        params.extend(link_params)

    # 直接属性过滤
    for key, value in direct_filters.items():
        prop = next((p for p in obj_def.properties if p.name == key), None)
        if not prop or not prop.column:
            continue
        col_ref = f"t0.{prop.column}"
        if fuzzy and prop.data_type == "TEXT" and not isinstance(value, dict):
            where_clauses.append(f"{col_ref} LIKE ?")
            params.append(f"%{value}%")
        else:
            where_clauses.append(_compile_condition(col_ref, value, params))

    # $or 条件（仅支持直接属性，可含运算符）
    if or_groups:
        or_clauses = []
        for branch in or_groups:
            branch_params: list = []
            branch_clauses: list[str] = []
            for key, value in branch.items():
                prop = next((p for p in obj_def.properties if p.name == key), None)
                if not prop or not prop.column:
                    continue
                col_ref = f"t0.{prop.column}"
                if fuzzy and prop.data_type == "TEXT" and not isinstance(value, dict):
                    branch_clauses.append(f"{col_ref} LIKE ?")
                    branch_params.append(f"%{value}%")
                else:
                    branch_clauses.append(_compile_condition(col_ref, value, branch_params))
            if branch_clauses:
                or_clauses.append("(" + " AND ".join(branch_clauses) + ")")
                params.extend(branch_params)
        if or_clauses:
            where_clauses.append("(" + " OR ".join(or_clauses) + ")")

    # ORDER BY：支持点号跨 Link，共享 join_cache
    order_col_ref: Optional[str] = None
    order_by_derived = False
    if order_by:
        if "." in order_by:
            # 跨 Link ORDER BY：复用 join_cache & alias_counter
            ob_parts = order_by.split(".")
            ob_prop_name = ob_parts[-1]
            ob_path = ob_parts[:-1]
            current_type = object_type
            current_alias = "t0"
            for segment in ob_path:
                cache_key = (current_alias, segment)
                if cache_key in join_cache:
                    current_alias = join_cache[cache_key]
                    link, _ = _find_link_by_segment(current_type, segment)
                    if link:
                        current_type = (link.target_type if link.source_type == current_type else link.source_type)
                    continue
                link, direction = _find_link_by_segment(current_type, segment)
                if link is None:
                    raise ValueError(f"排序路径 '{order_by}' 中无法从 '{current_type}' 找到 '{segment}'")
                new_alias = f"l{alias_counter[0]}"
                alias_counter[0] += 1
                if direction == "forward":
                    target_table = OBJECT_TYPES[link.target_type].table
                    join_clauses.append(
                        f"LEFT JOIN {target_table} {new_alias} "
                        f"ON {current_alias}.{link.source_fk} = {new_alias}.id"
                    )
                    current_type = link.target_type
                else:
                    source_table = OBJECT_TYPES[link.source_type].table
                    join_clauses.append(
                        f"LEFT JOIN {source_table} {new_alias} "
                        f"ON {current_alias}.id = {new_alias}.{link.source_fk}"
                    )
                    current_type = link.source_type
                join_cache[cache_key] = new_alias
                current_alias = new_alias

            ob_obj_def = OBJECT_TYPES.get(current_type)
            if ob_obj_def:
                ob_prop = next((p for p in ob_obj_def.properties if p.name == ob_prop_name), None)
                if ob_prop and ob_prop.prop_type != "derived":
                    order_col_ref = f"{current_alias}.{ob_prop.column}"
        else:
            order_prop = next((p for p in obj_def.properties if p.name == order_by), None)
            if order_prop and order_prop.prop_type == "derived":
                order_by_derived = True
            elif order_prop and order_prop.column:
                order_col_ref = f"t0.{order_prop.column}"

    # 当存在 JOIN 时加 DISTINCT，防止多对多行膨胀
    needs_distinct = bool(join_clauses) and not order_by_derived
    select_clause = f"SELECT {'DISTINCT ' if needs_distinct else ''}{cols_str} FROM {obj_def.table} t0"

    sql_parts = [select_clause]
    sql_parts.extend(join_clauses)

    if where_clauses:
        sql_parts.append("WHERE " + " AND ".join(where_clauses))

    if order_col_ref:
        direction = "DESC" if order_dir.lower() == "desc" else "ASC"
        sql_parts.append(f"ORDER BY {order_col_ref} {direction}")

    if order_by_derived:
        sql_parts.append("LIMIT 1000 OFFSET 0")
    else:
        sql_parts.append("LIMIT ? OFFSET ?")
        params.extend([limit, offset])

    sql = "\n".join(sql_parts)

    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for row in rows:
        obj = {"_objectType": object_type}
        for p in obj_def.properties:
            if p.prop_type != "derived" and p.column in row.keys():
                obj[p.name] = row[p.column]
            elif p.prop_type == "derived":
                obj[p.name] = None
        results.append(obj)

    fill_derived_batch(results, object_type)

    if order_by_derived:
        reverse = order_dir.lower() == "desc"
        results.sort(
            key=lambda x: (x.get(order_by) is None, x.get(order_by) or 0),
            reverse=reverse,
        )
        results = results[offset: offset + limit]

    return results


# ============================================================
# Aggregation 引擎 — 通用聚合查询（GROUP BY + 聚合函数）
# ============================================================

# 支持的聚合函数
_AGG_FUNC_MAP = {
    "count": "COUNT(*)",
    "count_distinct": "COUNT(DISTINCT {col})",
    "sum": "SUM({col})",
    "avg": "AVG({col})",
    "min": "MIN({col})",
    "max": "MAX({col})",
}


def aggregate_objects(
    object_type: str,
    aggregations: list[dict],
    filters: Optional[dict] = None,
    group_by: Optional[list[str]] = None,
    order_by: Optional[str] = None,
    order_dir: str = "desc",
    limit: int = 50,
) -> dict:
    """通用聚合查询，支持跨 Link 的分组和过滤。

    参数:
        object_type: 基础对象类型（如 "Score"）
        aggregations: 聚合定义列表，每项格式:
            {"type": "avg", "field": "scoreValue", "name": "avg_score"}
            type 可选: count, count_distinct, sum, avg, min, max
            field: 属性名（支持跨Link点号如 "student.age"），count 不需要 field
            name: 结果别名（可选，默认自动生成）
        filters: 过滤条件（格式同 query_objects_v2，支持跨 Link 点号）
        group_by: 分组字段列表，支持跨 Link 点号（如 ["student.name", "course.name"]）
        order_by: 排序字段（引用 aggregation 的 name，或 group_by 字段）
        order_dir: 排序方向 "asc" / "desc"
        limit: 返回上限

    返回:
        {"success": True, "data": [...], "sql": "...(debug)"}
    """
    obj_def = OBJECT_TYPES.get(object_type)
    if not obj_def:
        return {"success": False, "error": f"Unknown object type: {object_type}"}

    if not aggregations:
        return {"success": False, "error": "aggregations 不能为空"}

    # 共享 JOIN 状态
    join_clauses: list[str] = []
    join_cache: dict = {}
    alias_counter = [1]
    params: list = []

    # --- 编译 aggregation SELECT 子句 ---
    select_parts: list[str] = []
    agg_aliases: list[str] = []  # 对应位置的别名
    for i, agg in enumerate(aggregations):
        agg_type = agg.get("type", "count").lower()
        agg_field = agg.get("field")
        agg_name = agg.get("name", f"{agg_type}_{i}")
        agg_aliases.append(agg_name)

        if agg_type not in _AGG_FUNC_MAP:
            return {"success": False, "error": f"不支持的聚合类型: {agg_type}，可用: {list(_AGG_FUNC_MAP.keys())}"}

        if agg_type == "count" and not agg_field:
            select_parts.append(f"COUNT(*) AS {agg_name}")
        else:
            if not agg_field:
                return {"success": False, "error": f"聚合类型 '{agg_type}' 需要指定 field"}
            col_ref = _resolve_field_ref(
                object_type, agg_field, join_clauses, join_cache, alias_counter
            )
            template = _AGG_FUNC_MAP[agg_type]
            select_parts.append(f"{template.format(col=col_ref)} AS {agg_name}")

    # --- 编译 GROUP BY 子句 ---
    group_refs: list[str] = []
    group_select_parts: list[str] = []
    if group_by:
        for g_field in group_by:
            col_ref = _resolve_field_ref(
                object_type, g_field, join_clauses, join_cache, alias_counter
            )
            group_refs.append(col_ref)
            # 用最后一段属性名作别名
            alias = g_field.replace(".", "_")
            group_select_parts.append(f"{col_ref} AS {alias}")

    # --- 编译 WHERE 子句（过滤）---
    where_clauses: list[str] = []
    if filters:
        filters = dict(filters)
        direct_filters = {}
        link_filters = {}
        for key, value in filters.items():
            if "." in key:
                link_filters[key] = value
            else:
                direct_filters[key] = value

        if link_filters:
            _, link_where, link_params = _build_link_joins(
                object_type, link_filters, False,
                join_clauses, join_cache, alias_counter,
            )
            where_clauses.extend(link_where)
            params.extend(link_params)

        for key, value in direct_filters.items():
            prop = next((p for p in obj_def.properties if p.name == key), None)
            if not prop or not prop.column:
                continue
            col_ref = f"t0.{prop.column}"
            where_clauses.append(_compile_condition(col_ref, value, params))

    # --- 组装 SQL ---
    all_select = group_select_parts + select_parts
    sql_parts = [f"SELECT {', '.join(all_select)} FROM {obj_def.table} t0"]
    sql_parts.extend(join_clauses)

    if where_clauses:
        sql_parts.append("WHERE " + " AND ".join(where_clauses))

    if group_refs:
        sql_parts.append("GROUP BY " + ", ".join(group_refs))

    # ORDER BY
    direction = "DESC" if order_dir.lower() == "desc" else "ASC"
    if order_by:
        # order_by 可以引用 agg 别名或 group_by 字段别名
        sql_parts.append(f"ORDER BY {order_by} {direction}")
    elif agg_aliases:
        # 默认按第一个聚合结果排序
        sql_parts.append(f"ORDER BY {agg_aliases[0]} {direction}")

    sql_parts.append(f"LIMIT {limit}")

    sql = "\n".join(sql_parts)

    # --- 执行 ---
    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
    except Exception as e:
        conn.close()
        return {"success": False, "error": str(e), "sql": sql}
    conn.close()

    results = [dict(row) for row in rows]
    return {"success": True, "data": results, "sql": sql}


def _resolve_field_ref(
    object_type: str,
    field_path: str,
    join_clauses: list,
    join_cache: dict,
    alias_counter: list,
) -> str:
    """将字段路径（如 "student.name" 或 "scoreValue"）解析为 SQL 列引用。

    复用已有的 _build_link_joins / _find_link_by_segment 机制。
    """
    if "." in field_path:
        parts = field_path.split(".")
        prop_name = parts[-1]
        path_segments = parts[:-1]

        current_type = object_type
        current_alias = "t0"

        for segment in path_segments:
            cache_key = (current_alias, segment)
            if cache_key in join_cache:
                current_alias = join_cache[cache_key]
                link, _ = _find_link_by_segment(current_type, segment)
                if link:
                    current_type = (
                        link.target_type
                        if link.source_type == current_type
                        else link.source_type
                    )
                continue

            link, direction = _find_link_by_segment(current_type, segment)
            if link is None:
                raise ValueError(f"无法从 '{current_type}' 解析路径段 '{segment}'")

            new_alias = f"l{alias_counter[0]}"
            alias_counter[0] += 1

            if direction == "forward":
                target_table = OBJECT_TYPES[link.target_type].table
                join_clauses.append(
                    f"JOIN {target_table} {new_alias} "
                    f"ON {current_alias}.{link.source_fk} = {new_alias}.id"
                )
                current_type = link.target_type
            else:
                source_table = OBJECT_TYPES[link.source_type].table
                join_clauses.append(
                    f"JOIN {source_table} {new_alias} "
                    f"ON {current_alias}.id = {new_alias}.{link.source_fk}"
                )
                current_type = link.source_type

            join_cache[cache_key] = new_alias
            current_alias = new_alias

        # 解析最终属性
        target_obj_def = OBJECT_TYPES[current_type]
        prop = next(
            (p for p in target_obj_def.properties if p.name == prop_name), None
        )
        if not prop:
            raise ValueError(f"属性 '{prop_name}' 在类型 '{current_type}' 中不存在")
        return f"{current_alias}.{prop.column}"
    else:
        # 直接属性
        obj_def = OBJECT_TYPES[object_type]
        prop = next((p for p in obj_def.properties if p.name == field_path), None)
        if not prop:
            raise ValueError(f"属性 '{field_path}' 在类型 '{object_type}' 中不存在")
        return f"t0.{prop.column}"


def query_object_set(
    set_name: str,
    filters: Optional[dict] = None,
    limit: int = 50,
) -> dict:
    """查询一个预定义的 ObjectSet。"""
    from ontology_engine.registry import OBJECT_SETS

    obj_set = OBJECT_SETS.get(set_name)
    if not obj_set:
        return {"success": False, "error": f"Unknown ObjectSet: {set_name}"}

    obj_def = OBJECT_TYPES[obj_set.object_type]
    regular_cols = [
        p.column
        for p in obj_def.properties
        if p.prop_type in ("primary_key", "regular")
    ]
    cols_str = ", ".join(f"o.{c}" for c in regular_cols)

    sql = f"""
        SELECT {cols_str}
        FROM ({obj_set.sql.strip()}) _subset
        JOIN {obj_def.table} o ON o.id = _subset.id
    """
    params = []
    where_clauses = []

    if filters:
        for key, value in filters.items():
            prop = next((p for p in obj_def.properties if p.name == key), None)
            if prop and prop.column:
                where_clauses.append(f"o.{prop.column} = ?")
                params.append(value)
        if where_clauses:
            sql += " WHERE " + " AND ".join(where_clauses)

    sql += " LIMIT ?"
    params.append(limit)

    conn = get_connection()
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    results = []
    for row in rows:
        obj = {"_objectType": obj_set.object_type}
        for p in obj_def.properties:
            if p.prop_type != "derived" and p.column in row.keys():
                obj[p.name] = row[p.column]
            elif p.prop_type == "derived":
                obj[p.name] = None
        results.append(obj)

    fill_derived_batch(results, obj_set.object_type)
    return {"success": True, "data": results, "object_set": set_name}
