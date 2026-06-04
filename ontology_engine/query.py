"""
查询引擎 — 将 Ontology 语义操作（查 Object、遍历 Link）翻译为 SQL。
这是「语义表示层用 Ontology，计算层用 SQL」的核心体现。
"""

from typing import Optional
from ontology_engine.database import get_connection
from ontology_engine.registry import OBJECT_TYPES, LINK_TYPES


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
    query_type: str, link_filters: dict, fuzzy: bool = False
) -> tuple[list[str], list[str], list]:
    """根据点号过滤器构建 SQL JOIN 链。

    对 filter key "course.teacher.name"：
    1. 拆分为路径段 ["course", "teacher"]，最终属性 "name"
    2. 逐段解析 LinkTypeDef，添加 JOIN 子句
    3. 在最终表上添加 WHERE 条件

    去重：相同路径前缀共享同一个 JOIN（如 student.name + student.className）。

    Returns (join_clauses, where_clauses, params).
    """
    join_clauses = []
    where_clauses = []
    params = []
    join_cache: dict[tuple[str, str], str] = {}  # (alias, segment) → new_alias
    alias_counter = [1]

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

        col = prop.column
        if fuzzy and prop.data_type == "TEXT":
            where_clauses.append(f"{current_alias}.{col} LIKE ?")
            params.append(f"%{value}%")
        else:
            where_clauses.append(f"{current_alias}.{col} = ?")
            params.append(value)

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
    """跨 Link 查询对象，支持点号链式过滤。

    三种 filter 格式：
    - 直接属性: {"name": "张三", "age": 20}
    - 单跳 Link: {"student.name": "张三", "course.name": "数学"}
    - 多跳 Link: {"course.teacher.department": "理学院"}

    引擎通过 registry.py 的 LINK_TYPES 自动解析路径，编译为 SQL JOIN。
    """
    obj_def = OBJECT_TYPES[object_type]
    if not obj_def:
        raise ValueError(f"Unknown object type: {object_type}")

    # 拆分直接过滤和跨 Link 过滤
    direct_filters = {}
    link_filters = {}
    if filters:
        for key, value in filters.items():
            if "." in key:
                link_filters[key] = value
            else:
                direct_filters[key] = value

    # 基表别名 t0
    regular_cols = [
        p.column
        for p in obj_def.properties
        if p.prop_type in ("primary_key", "regular")
    ]
    cols_str = ", ".join(f"t0.{c}" for c in regular_cols)
    sql_parts = [f"SELECT {cols_str} FROM {obj_def.table} t0"]
    params = []
    where_clauses = []

    # 从 link filters 构建 JOIN
    if link_filters:
        join_clauses, link_where, link_params = _build_link_joins(
            object_type, link_filters, fuzzy
        )
        sql_parts.extend(join_clauses)
        where_clauses.extend(link_where)
        params.extend(link_params)

    # 直接属性过滤（在基表上）
    for key, value in direct_filters.items():
        prop = next((p for p in obj_def.properties if p.name == key), None)
        if not prop or not prop.column:
            continue
        if fuzzy and prop.data_type == "TEXT":
            where_clauses.append(f"t0.{prop.column} LIKE ?")
            params.append(f"%{value}%")
        else:
            where_clauses.append(f"t0.{prop.column} = ?")
            params.append(value)

    if where_clauses:
        sql_parts.append("WHERE " + " AND ".join(where_clauses))

    # 判断是否为派生属性排序（派生属性在 Python 层计算，无法用 SQL ORDER BY）
    order_by_derived = False
    if order_by:
        order_prop = next((p for p in obj_def.properties if p.name == order_by), None)
        if order_prop and order_prop.prop_type == "derived":
            order_by_derived = True
        else:
            col = f"t0.{order_prop.column}" if order_prop and order_prop.column else order_by
            direction = "DESC" if order_dir.lower() == "desc" else "ASC"
            sql_parts.append(f"ORDER BY {col} {direction}")

    if order_by_derived:
        # 派生属性排序：先取所有匹配行（含安全上限），fill 后 Python 排序再切片
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

    # 派生属性排序：fill 完成后在 Python 层排序，再应用 limit/offset
    if order_by_derived:
        reverse = order_dir.lower() == "desc"
        results.sort(
            key=lambda x: (x.get(order_by) is None, x.get(order_by) or 0),
            reverse=reverse
        )
        results = results[offset: offset + limit]

    return results


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
