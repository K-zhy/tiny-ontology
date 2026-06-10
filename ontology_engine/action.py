"""
Action 引擎 — 执行 Ontology Action（校验 → 事务 → 审计）。
所有写操作必须通过 Action，不直接操作数据库表。
"""

import json
from ontology_engine.database import get_connection
from ontology_engine.registry import ACTION_TYPES, OBJECT_TYPES, LINK_TYPES


def execute_action(action_name: str, params: dict, operator: str = "system") -> dict:
    """执行一个 Action，返回结果字典"""
    action_def = ACTION_TYPES.get(action_name)
    if not action_def:
        return {"success": False, "error": f"Unknown action: {action_name}"}

    # Step 1: 参数校验
    for p in action_def.params:
        if p.required and p.name not in params:
            return {"success": False, "error": f"Missing required param: {p.name}"}

    conn = get_connection()
    try:
        # Step 2: 业务校验
        if action_def.validation_func:
            valid, msg = _run_validation(action_def.validation_func, params)
            if not valid:
                conn.close()
                return {"success": False, "error": msg}

        # Step 3: 事务性执行
        result = _run_action(conn, action_def, params)

        # Step 4: 审计日志
        conn.execute(
            "INSERT INTO audit_log (action_name, operator, params, result) VALUES (?, ?, ?, ?)",
            (action_name, operator, json.dumps(params, ensure_ascii=False),
             json.dumps(result, ensure_ascii=False))
        )
        conn.commit()
        result["success"] = True
        result["audited"] = True
        return result

    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _run_validation(func_name: str, params: dict) -> tuple[bool, str]:
    """执行业务校验 Function"""
    if func_name == "validateScore":
        student_sno = params.get("studentSno")
        course_cno = params.get("courseCno")
        score_value = params.get("scoreValue")

        # 分值范围校验
        if score_value is not None and (score_value < 0 or score_value > 100):
            return False, "成绩必须在 0-100 之间"

        # 重复录入校验
        conn = get_connection()
        row = conn.execute(
            "SELECT id FROM score WHERE Sno = ? AND Cno = ?",
            (student_sno, course_cno)
        ).fetchone()
        conn.close()
        if row:
            return False, f"该学生(Sno={student_sno})在该课程(Cno={course_cno})已有成绩记录(id={row['id']})，不能重复录入"

        return True, ""
    return True, ""


def _run_action(conn, action_def, params: dict) -> dict:
    """在事务中执行具体操作"""
    name = action_def.api_name

    if name == "createScore":
        next_score_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM score").fetchone()[0]
        conn.execute(
            "INSERT INTO score (id, Sno, Cno, score_value, exam_date) VALUES (?, ?, ?, ?, ?)",
            (next_score_id, params["studentSno"], params["courseCno"], params["scoreValue"], params["examDate"])
        )
        return {"scoreId": next_score_id, "message": "成绩录入成功"}

    elif name == "updateScore":
        updates = []
        values = []
        if "scoreValue" in params and params["scoreValue"] is not None:
            updates.append("score_value = ?")
            values.append(params["scoreValue"])
        if "examDate" in params and params["examDate"] is not None:
            updates.append("exam_date = ?")
            values.append(params["examDate"])
        values.append(params["scoreId"])
        conn.execute(
            f"UPDATE score SET {', '.join(updates)} WHERE id = ?", values
        )
        return {"message": "成绩修改成功"}

    elif name == "deleteScore":
        conn.execute("DELETE FROM score WHERE id = ?", (params["scoreId"],))
        return {"message": "成绩删除成功"}

    elif name == "assignTeacher":
        next_tc_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM tc").fetchone()[0]
        semester = params.get("semester")
        conn.execute(
            "INSERT OR IGNORE INTO tc (id, Cno, Tno, semester) VALUES (?, ?, ?, ?)",
            (next_tc_id, params["courseCno"], params["teacherTno"], semester)
        )
        return {"message": "教师授课关系创建成功"}

    return {"message": "Action executed"}
