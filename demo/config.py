"""
学生成绩 Demo — OAG 领域配置
=============================
定义 OntologyConfig 实例 + Score 富化函数。
由 demo/__init__.py 在 load() 时导出，供 nl_oag.py 组装 Pipeline 时使用。
"""
from ontology_engine.database import get_connection
from ontology_engine.oag.config import OntologyConfig


def _enrich_score_context(results: list[dict]) -> None:
    """为 Score 对象批量补充 studentName、courseName、teacherName。"""
    if not results or results[0].get("_objectType") != "Score":
        return
    obj_ids = [obj["id"] for obj in results if obj.get("id")]
    if not obj_ids:
        return

    conn = get_connection()
    placeholders = ",".join("?" * len(obj_ids))
    fk_rows = conn.execute(
        f"SELECT id, Sno, Cno FROM score WHERE id IN ({placeholders})", tuple(obj_ids)
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
            f"SELECT Sno, name FROM student WHERE Sno IN ({','.join('?' * len(sids))})",
            tuple(sids)
        ).fetchall()
        s_names = {r["Sno"]: r["name"] for r in rows}
        conn.close()
    if cids:
        conn = get_connection()
        rows = conn.execute(
            f"SELECT Cno, name FROM course WHERE Cno IN ({','.join('?' * len(cids))})",
            tuple(cids)
        ).fetchall()
        for r in rows:
            c_names[r["Cno"]] = r["name"]
        tc_rows = conn.execute(
            f"SELECT tc.Cno, t.name FROM tc JOIN teacher t ON tc.Tno = t.Tno "
            f"WHERE tc.Cno IN ({','.join('?' * len(cids))})",
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


def _enrich_teaching_assignment_context(results: list[dict]) -> None:
    """为 TeachingAssignment 对象批量补充 courseName、teacherName。"""
    if not results or results[0].get("_objectType") != "TeachingAssignment":
        return

    course_ids = {obj.get("courseCno") for obj in results if obj.get("courseCno")}
    teacher_ids = {obj.get("teacherTno") for obj in results if obj.get("teacherTno")}
    if not course_ids and not teacher_ids:
        return

    course_names: dict[str, str] = {}
    teacher_names: dict[str, str] = {}
    conn = get_connection()
    try:
        if course_ids:
            rows = conn.execute(
                f"SELECT Cno, name FROM course WHERE Cno IN ({','.join('?' * len(course_ids))})",
                tuple(course_ids),
            ).fetchall()
            course_names = {row["Cno"]: row["name"] for row in rows}
        if teacher_ids:
            rows = conn.execute(
                f"SELECT Tno, name FROM teacher WHERE Tno IN ({','.join('?' * len(teacher_ids))})",
                tuple(teacher_ids),
            ).fetchall()
            teacher_names = {row["Tno"]: row["name"] for row in rows}
    finally:
        conn.close()

    for obj in results:
        course_id = obj.get("courseCno")
        teacher_id = obj.get("teacherTno")
        if course_id in course_names:
            obj["courseName"] = course_names[course_id]
        if teacher_id in teacher_names:
            obj["teacherName"] = teacher_names[teacher_id]


def _enrich_context(results: list[dict]) -> None:
    if not results:
        return
    object_type = results[0].get("_objectType")
    if object_type == "Score":
        _enrich_score_context(results)
    elif object_type == "TeachingAssignment":
        _enrich_teaching_assignment_context(results)


# ---- 学生成绩 Demo 的完整 OntologyConfig ----

DEMO_OAG_CONFIG = OntologyConfig(
    type_aliases={
        "学生": "Student", "教师": "Teacher", "课程": "Course",
        "成绩": "Score", "分数": "Score",
        "授课安排": "TeachingAssignment", "授课关系": "TeachingAssignment",
        "任课安排": "TeachingAssignment", "开课安排": "TeachingAssignment",
    },
    value_aliases={
        "gender": {
            "男": "M", "男性": "M", "male": "M", "m": "M",
            "女": "F", "女性": "F", "female": "F", "f": "F",
        }
    },
    extra_type_keywords={
        "Student": ["同学", "平均分", "avgscore", "学号"],
        "Teacher": ["老师", "讲师", "教授", "任课"],
        "Course":  ["科目", "学分", "通过率", "passrate"],
        "TeachingAssignment": ["学期", "授课", "共同授课", "任课安排", "开课", "开课安排"],
        "Score":   ["成绩", "分数", "考试", "不及格", "挂科", "高分", "低分"],
    },
    type_expansion_rules={
        "Score": ["Student", "Course"],
        "Course": ["TeachingAssignment"],
        "Teacher": ["TeachingAssignment"],
    },
    result_enricher=_enrich_context,
    system_prompt_addendum=(
        "Score 查询结果会自动补充 studentName、courseName、teacherName，"
        "不要再重复查询 Student 或 Course 只为拿名称。"
        "涉及学期、授课安排、共同授课时，优先查询 TeachingAssignment。"
    ),
)
