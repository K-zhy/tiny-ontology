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
