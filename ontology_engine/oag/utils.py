"""OAG 共享工具函数：类型别名、过滤条件规范化、Score 上下文富化。"""
from __future__ import annotations
from ontology_engine.database import get_connection

# ---- 别名映射（可在外部扩展） ----

TYPE_ALIASES: dict[str, str] = {
    "学生": "Student", "教师": "Teacher", "课程": "Course", "成绩": "Score", "分数": "Score",
}

VALUE_ALIASES: dict[str, dict[str, str]] = {
    "gender": {
        "男": "M", "男性": "M", "male": "M", "m": "M",
        "女": "F", "女性": "F", "female": "F", "f": "F",
    }
}


# ---- 过滤条件规范化 ----

def normalize_filter_value(prop_name: str, value):
    if isinstance(value, str):
        alias_map = VALUE_ALIASES.get(prop_name)
        if alias_map:
            return alias_map.get(value.lower(), alias_map.get(value, value))
        return value
    if isinstance(value, list):
        return [normalize_filter_value(prop_name, item) for item in value]
    if isinstance(value, dict):
        return {
            k: normalize_filter_value(prop_name, v) if k == "value" else v
            for k, v in value.items()
        }
    return value


def normalize_filters(filters: dict) -> dict:
    normalized = {}
    for key, value in filters.items():
        if key == "$or" and isinstance(value, list):
            normalized[key] = [
                normalize_filters(item) if isinstance(item, dict) else item
                for item in value
            ]
            continue
        prop_name = key.split(".")[-1]
        normalized[key] = normalize_filter_value(prop_name, value)
    return normalized


# ---- Score 上下文富化 ----

def enrich_score_context(results: list[dict]) -> None:
    """为 Score 对象批量补充 studentName、courseName、teacherName。"""
    if not results or results[0].get("_objectType") != "Score":
        return
    obj_ids = [obj["id"] for obj in results if obj.get("id")]
    if not obj_ids:
        return

    conn = get_connection()
    placeholders = ",".join("?" * len(obj_ids))
    fk_rows = conn.execute(
        f"SELECT id, Sno, Cno FROM score WHERE id IN ({placeholders})",
        tuple(obj_ids)
    ).fetchall()
    conn.close()

    id_to_fk = {r["id"]: (r["Sno"], r["Cno"]) for r in fk_rows}
    sids, cids = set(), set()
    for obj in results:
        fk = id_to_fk.get(obj["id"])
        if fk:
            sid, cid = fk
            obj["studentSno"] = sid
            obj["courseCno"] = cid
            if sid:
                sids.add(sid)
            if cid:
                cids.add(cid)

    s_names: dict = {}
    c_names: dict = {}
    c_teachers: dict = {}

    if sids:
        conn = get_connection()
        rows = conn.execute(
            f"SELECT Sno, name FROM student WHERE Sno IN ({','.join('?'*len(sids))})",
            tuple(sids)
        ).fetchall()
        s_names = {r["Sno"]: r["name"] for r in rows}
        conn.close()

    if cids:
        conn = get_connection()
        rows = conn.execute(
            f"SELECT Cno, name FROM course WHERE Cno IN ({','.join('?'*len(cids))})",
            tuple(cids)
        ).fetchall()
        for r in rows:
            c_names[r["Cno"]] = r["name"]
        tc_rows = conn.execute(
            f"SELECT tc.Cno, t.name FROM tc JOIN teacher t ON tc.Tno = t.Tno "
            f"WHERE tc.Cno IN ({','.join('?'*len(cids))})",
            tuple(cids)
        ).fetchall()
        for row in tc_rows:
            c_teachers.setdefault(row["Cno"], []).append(row["name"])
        conn.close()

    for obj in results:
        sid = obj.get("studentSno") or obj.get("Sno")
        cid = obj.get("courseCno") or obj.get("Cno")
        if sid and sid in s_names:
            obj["studentName"] = s_names[sid]
        if cid and cid in c_names:
            obj["courseName"] = c_names[cid]
            if cid in c_teachers:
                obj["teacherName"] = "、".join(c_teachers[cid])
