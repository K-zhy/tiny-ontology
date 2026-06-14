"""学生成绩 Demo 的 Function handler。"""

from ontology_engine.database import get_connection
from ontology_engine.functions import register_function_handler
from ontology_engine.registry import FUNCTIONS

from .validation_handlers import validate_score


def get_top_students(params: dict) -> dict:
    func_def = FUNCTIONS["getTopStudents"]
    course_cno = params.get("courseCno")
    limit = params.get("limit") or 10
    conn = get_connection()
    rows = conn.execute(func_def.sql_template.strip(), (course_cno, limit)).fetchall()
    conn.close()
    return {"success": True, "data": [dict(row) for row in rows]}


def search_by_name(params: dict) -> dict:
    func_def = FUNCTIONS["searchByName"]
    keyword = params.get("keyword") or ""
    conn = get_connection()
    rows = conn.execute(func_def.sql_template.strip(), (keyword, keyword, keyword)).fetchall()
    conn.close()
    return {"success": True, "data": [dict(row) for row in rows]}


def get_score_summary(params: dict) -> dict:
    object_type = params.get("objectType", "")
    object_id = params.get("objectId")
    if object_type == "Student":
        sql = "SELECT MAX(score_value) as max_score, MIN(score_value) as min_score, ROUND(AVG(score_value),1) as avg_score, COUNT(*) as count FROM score WHERE Sno = ?"
    elif object_type == "Course":
        sql = "SELECT MAX(score_value) as max_score, MIN(score_value) as min_score, ROUND(AVG(score_value),1) as avg_score, COUNT(*) as count FROM score WHERE Cno = ?"
    else:
        return {"success": False, "error": f"Unknown object type for Scoreable: {object_type}"}

    conn = get_connection()
    row = conn.execute(sql, (object_id,)).fetchone()
    conn.close()
    if row:
        return {"success": True, "data": dict(row)}
    return {"success": True, "data": {"max_score": None, "min_score": None, "avg_score": None, "count": 0}}


def validate_score_function(params: dict) -> dict:
    valid, message = validate_score(params)
    return {"success": True, "data": {"valid": valid, "message": message or "校验通过"}}


def register_function_handlers() -> None:
    register_function_handler("getTopStudents", get_top_students)
    register_function_handler("searchByName", search_by_name)
    register_function_handler("getScoreSummary", get_score_summary)
    register_function_handler("validateScore", validate_score_function)
