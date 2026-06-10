"""
Function 引擎 — 执行 Ontology Function（SQL 实现的计算逻辑）。
所有 Function 内部用 SQL 实现，对外暴露为业务语义的派生属性或查询接口。
"""

from typing import Optional
from ontology_engine.database import get_connection
from ontology_engine.registry import FUNCTIONS


def call_function(func_name: str, params: Optional[dict] = None) -> dict:
    """调用一个 Function"""
    params = params or {}
    func_def = FUNCTIONS.get(func_name)
    if not func_def:
        return {"success": False, "error": f"Unknown function: {func_name}"}

    # 填充参数（位置参数按定义顺序）
    sql_params = []
    for p in func_def.params:
        val = params.get(p.name)
        if val is None and p.required:
            return {"success": False, "error": f"Missing param: {p.name}"}
        sql_params.append(val)

    conn = get_connection()
    try:
        if func_def.func_type == "validation":
            return _run_validation(func_name, params)

        if func_def.func_type == "object_set":
            # 批量 Function：返回多行结果
            if func_name == "getTopStudents" and sql_params[1] is None:
                sql_params[1] = 10
            if func_name == "searchByName":
                # searchByName SQL 有三个 ? (每 UNION 一个)，用同一个 keyword
                kw = sql_params[0] if sql_params[0] else ""
                sql_params = [kw, kw, kw]
            rows = conn.execute(func_def.sql_template.strip(), sql_params).fetchall()
            results = [dict(row) for row in rows]
            conn.close()
            return {"success": True, "data": results}

        if func_name == "getScoreSummary":
            obj_type = params.get("objectType", "")
            obj_id = params.get("objectId")
            if obj_type == "Student":
                row = conn.execute(
                    "SELECT MAX(score_value) as max_score, MIN(score_value) as min_score, ROUND(AVG(score_value),1) as avg_score, COUNT(*) as count FROM score WHERE Sno = ?",
                    (obj_id,)
                ).fetchone()
            elif obj_type == "Course":
                row = conn.execute(
                    "SELECT MAX(score_value) as max_score, MIN(score_value) as min_score, ROUND(AVG(score_value),1) as avg_score, COUNT(*) as count FROM score WHERE Cno = ?",
                    (obj_id,)
                ).fetchone()
            else:
                conn.close()
                return {"success": False, "error": f"Unknown object type for Scoreable: {obj_type}"}
            conn.close()
            if row:
                return {"success": True, "data": dict(row)}
            return {"success": True, "data": {"max_score": None, "min_score": None, "avg_score": None, "count": 0}}

        # 标量 Function（getAvgScore, getPassRate, getCourseAvgScore）
        row = conn.execute(func_def.sql_template.strip(), sql_params).fetchone()
        conn.close()
        val = row[0] if row else None
        return {"success": True, "data": val}
    except Exception as e:
        conn.close()
        return {"success": False, "error": str(e)}


def compute_derived_property(object_type: str, object_id: int, prop_name: str):
    """计算单个对象的派生属性"""
    for func_def in FUNCTIONS.values():
        if (func_def.is_derived_property == prop_name
                and func_def.bound_object == object_type):
            result = call_function(func_def.api_name,
                                  {func_def.params[0].name: object_id})
            if result.get("success"):
                return result["data"]
    return None


def _run_validation(func_name: str, params: dict) -> dict:
    """校验 Function 的独立调用"""
    if func_name == "validateScore":
        student_sno = params.get("studentSno")
        course_cno = params.get("courseCno")
        score_value = params.get("scoreValue")

        errors = []
        if score_value is not None and (score_value < 0 or score_value > 100):
            errors.append("成绩必须在 0-100 之间")

        conn = get_connection()
        row = conn.execute(
            "SELECT id FROM score WHERE Sno = ? AND Cno = ?",
            (student_sno, course_cno)
        ).fetchone()
        conn.close()
        if row:
            errors.append(f"该学生已在该课程有成绩记录(id={row['id']})")

        if errors:
            return {"success": True, "data": {"valid": False, "message": "; ".join(errors)}}
        return {"success": True, "data": {"valid": True, "message": "校验通过"}}

    return {"success": True, "data": {"valid": True, "message": "ok"}}
