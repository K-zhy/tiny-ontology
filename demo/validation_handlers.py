"""学生成绩 Demo 的业务校验 handler。"""

from ontology_engine.action import register_validation_handler
from ontology_engine.database import get_connection


def validate_score(params: dict) -> tuple[bool, str]:
    student_sno = params.get("studentSno")
    course_cno = params.get("courseCno")
    score_value = params.get("scoreValue")

    if score_value is not None and (score_value < 0 or score_value > 100):
        return False, "成绩必须在 0-100 之间"

    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM score WHERE Sno = ? AND Cno = ?",
        (student_sno, course_cno),
    ).fetchone()
    conn.close()
    if row:
        return False, f"该学生(Sno={student_sno})在该课程(Cno={course_cno})已有成绩记录，不能重复录入"

    return True, ""


def register_validation_handlers() -> None:
    register_validation_handler("validateScore", validate_score)
