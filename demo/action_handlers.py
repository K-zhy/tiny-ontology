"""学生成绩 Demo 的 Action handler。"""

from ontology_engine.action import register_action_handler


def create_score(conn, params: dict) -> dict:
    next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM score").fetchone()[0]
    conn.execute(
        "INSERT INTO score (id, Sno, Cno, score_value, exam_date) VALUES (?, ?, ?, ?, ?)",
        (next_id, params["studentSno"], params["courseCno"], params["scoreValue"], params["examDate"]),
    )
    return {"scoreId": next_id, "message": "成绩录入成功"}


def update_score(conn, params: dict) -> dict:
    updates, values = [], []
    if "scoreValue" in params and params["scoreValue"] is not None:
        updates.append("score_value = ?")
        values.append(params["scoreValue"])
    if "examDate" in params and params["examDate"] is not None:
        updates.append("exam_date = ?")
        values.append(params["examDate"])
    if not updates:
        raise ValueError("没有可更新的成绩字段")

    values.append(params["scoreId"])
    conn.execute(f"UPDATE score SET {', '.join(updates)} WHERE id = ?", values)
    return {"message": "成绩修改成功"}


def delete_score(conn, params: dict) -> dict:
    conn.execute("DELETE FROM score WHERE id = ?", (params["scoreId"],))
    return {"message": "成绩删除成功"}


def assign_teacher(conn, params: dict) -> dict:
    next_id = conn.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM tc").fetchone()[0]
    conn.execute(
        "INSERT OR IGNORE INTO tc (id, Cno, Tno, semester) VALUES (?, ?, ?, ?)",
        (next_id, params["courseCno"], params["teacherTno"], params.get("semester")),
    )
    return {"message": "教师授课关系创建成功"}


def register_action_handlers() -> None:
    register_action_handler("createScore", create_score)
    register_action_handler("updateScore", update_score)
    register_action_handler("deleteScore", delete_score)
    register_action_handler("assignTeacher", assign_teacher)
