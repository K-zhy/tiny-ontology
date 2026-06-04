"""种子数据 — 预置学生、教师、课程和成绩"""
from ontology_engine.database import init_db, get_connection


def seed():
    init_db()
    conn = get_connection()

    # 清理旧数据
    for t in ["score", "course", "teacher", "student", "audit_log"]:
        conn.execute(f"DELETE FROM {t}")

    # 教师
    conn.execute("INSERT INTO teacher (id, name, subject, department) VALUES (1, '张教授', '数学', '理学院')")
    conn.execute("INSERT INTO teacher (id, name, subject, department) VALUES (2, '李教授', '英语', '外语学院')")
    conn.execute("INSERT INTO teacher (id, name, subject, department) VALUES (3, '王教授', '计算机科学', '信息学院')")

    # 课程
    conn.execute("INSERT INTO course (id, name, teacher_id, credit, semester) VALUES (1, '高等数学', 1, 4, '2024-春')")
    conn.execute("INSERT INTO course (id, name, teacher_id, credit, semester) VALUES (2, '线性代数', 1, 3, '2024-春')")
    conn.execute("INSERT INTO course (id, name, teacher_id, credit, semester) VALUES (3, '大学英语', 2, 2, '2024-春')")
    conn.execute("INSERT INTO course (id, name, teacher_id, credit, semester) VALUES (4, '数据结构', 3, 4, '2024-春')")
    conn.execute("INSERT INTO course (id, name, teacher_id, credit, semester) VALUES (5, 'Python编程', 3, 3, '2024-秋')")

    # 学生
    conn.execute("INSERT INTO student (id, name, age, gender, class_name) VALUES (1, '张三', 20, 'M', '计算机2201')")
    conn.execute("INSERT INTO student (id, name, age, gender, class_name) VALUES (2, '李四', 21, 'M', '计算机2201')")
    conn.execute("INSERT INTO student (id, name, age, gender, class_name) VALUES (3, '王五', 20, 'F', '计算机2202')")
    conn.execute("INSERT INTO student (id, name, age, gender, class_name) VALUES (4, '赵六', 22, 'M', '数学2201')")
    conn.execute("INSERT INTO student (id, name, age, gender, class_name) VALUES (5, '孙七', 19, 'F', '英语2201')")

    # 成绩
    scores = [
        (1, 1, 95, "2024-06-15"), (1, 2, 88, "2024-06-16"), (1, 3, 72, "2024-06-17"),
        (1, 4, 91, "2024-06-18"), (1, 5, 85, "2024-12-20"),
        (2, 1, 62, "2024-06-15"), (2, 2, 55, "2024-06-16"), (2, 3, 78, "2024-06-17"),
        (2, 4, 45, "2024-06-18"),
        (3, 1, 88, "2024-06-15"), (3, 2, 91, "2024-06-16"), (3, 3, 95, "2024-06-17"),
        (3, 4, 82, "2024-06-18"), (3, 5, 90, "2024-12-20"),
        (4, 1, 73, "2024-06-15"), (4, 2, 81, "2024-06-16"), (4, 4, 67, "2024-06-18"),
        (5, 1, 59, "2024-06-15"), (5, 3, 91, "2024-06-17"), (5, 5, 77, "2024-12-20"),
    ]
    conn.executemany(
        "INSERT INTO score (student_id, course_id, score_value, exam_date) VALUES (?, ?, ?, ?)",
        scores
    )

    conn.commit()
    conn.close()
    print("Seed data loaded: 3 teachers, 5 courses, 5 students, 20 scores")


if __name__ == "__main__":
    seed()
