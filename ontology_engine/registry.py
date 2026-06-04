"""
Ontology Registry — 注册所有 Object/Link/Action/Function 定义。
这里是「原始数据表 → Ontology 语义模型」的映射配置。
"""

from ontology_engine.schema import (
    ObjectTypeDef, PropertyDef,
    LinkTypeDef,
    ActionTypeDef, ParamDef,
    FunctionDef,
    InterfaceDef,
    ObjectSetDef,
)

# ============================================================
# Object Types
# ============================================================

OBJECT_TYPES: dict[str, ObjectTypeDef] = {
    "Student": ObjectTypeDef(
        api_name="Student",
        display_name="学生",
        table="student",
        properties=[
            PropertyDef(name="id", prop_type="primary_key", column="id", data_type="INTEGER"),
            PropertyDef(name="name", prop_type="regular", column="name", data_type="TEXT"),
            PropertyDef(name="age", prop_type="regular", column="age", data_type="INTEGER"),
            PropertyDef(name="gender", prop_type="regular", column="gender", data_type="TEXT"),
            PropertyDef(name="className", prop_type="regular", column="class_name", data_type="TEXT"),
            PropertyDef(name="avgScore", prop_type="derived", column="", data_type="REAL"),
        ],
    ),
    "Teacher": ObjectTypeDef(
        api_name="Teacher",
        display_name="教师",
        table="teacher",
        properties=[
            PropertyDef(name="id", prop_type="primary_key", column="id", data_type="INTEGER"),
            PropertyDef(name="name", prop_type="regular", column="name", data_type="TEXT"),
            PropertyDef(name="subject", prop_type="regular", column="subject", data_type="TEXT"),
            PropertyDef(name="department", prop_type="regular", column="department", data_type="TEXT"),
        ],
    ),
    "Course": ObjectTypeDef(
        api_name="Course",
        display_name="课程",
        table="course",
        properties=[
            PropertyDef(name="id", prop_type="primary_key", column="id", data_type="INTEGER"),
            PropertyDef(name="name", prop_type="regular", column="name", data_type="TEXT"),
            PropertyDef(name="credit", prop_type="regular", column="credit", data_type="INTEGER"),
            PropertyDef(name="semester", prop_type="regular", column="semester", data_type="TEXT"),
            PropertyDef(name="passRate", prop_type="derived", column="", data_type="TEXT"),
        ],
    ),
    "Score": ObjectTypeDef(
        api_name="Score",
        display_name="成绩",
        table="score",
        properties=[
            PropertyDef(name="id", prop_type="primary_key", column="id", data_type="INTEGER"),
            PropertyDef(name="scoreValue", prop_type="regular", column="score_value", data_type="REAL"),
            PropertyDef(name="examDate", prop_type="regular", column="exam_date", data_type="TEXT"),
        ],
    ),
}

# ============================================================
# Link Types
# ============================================================

LINK_TYPES: dict[str, LinkTypeDef] = {
    "earnedBy": LinkTypeDef(
        api_name="earnedBy",
        display_name="成绩属于",
        source_type="Score",
        target_type="Student",
        cardinality="many_to_one",
        source_fk="student_id",
        reverse_name="scores",
    ),
    "forCourse": LinkTypeDef(
        api_name="forCourse",
        display_name="成绩对应课程",
        source_type="Score",
        target_type="Course",
        cardinality="many_to_one",
        source_fk="course_id",
        reverse_name="scores",
    ),
    "taughtBy": LinkTypeDef(
        api_name="taughtBy",
        display_name="授课教师",
        source_type="Course",
        target_type="Teacher",
        cardinality="many_to_one",
        source_fk="teacher_id",
        reverse_name="courses",
    ),
}

# ============================================================
# Action Types
# ============================================================

ACTION_TYPES: dict[str, ActionTypeDef] = {
    "createScore": ActionTypeDef(
        api_name="createScore",
        display_name="录入成绩",
        action_type="object",
        bound_object="Score",
        params=[
            ParamDef(name="studentId", param_type="integer"),
            ParamDef(name="courseId", param_type="integer"),
            ParamDef(name="scoreValue", param_type="float"),
            ParamDef(name="examDate", param_type="string"),
        ],
        validation_func="validateScore",
    ),
    "updateScore": ActionTypeDef(
        api_name="updateScore",
        display_name="修改成绩",
        action_type="object",
        bound_object="Score",
        params=[
            ParamDef(name="scoreId", param_type="integer"),
            ParamDef(name="scoreValue", param_type="float"),
            ParamDef(name="examDate", param_type="string", required=False),
        ],
    ),
    "deleteScore": ActionTypeDef(
        api_name="deleteScore",
        display_name="删除成绩",
        action_type="object",
        bound_object="Score",
        params=[
            ParamDef(name="scoreId", param_type="integer"),
        ],
    ),
    "assignTeacher": ActionTypeDef(
        api_name="assignTeacher",
        display_name="分配教师",
        action_type="link",
        bound_object="Course",
        params=[
            ParamDef(name="courseId", param_type="integer"),
            ParamDef(name="teacherId", param_type="integer"),
        ],
    ),
}

# ============================================================
# Functions
# ============================================================

FUNCTIONS: dict[str, FunctionDef] = {
    "getAvgScore": FunctionDef(
        api_name="getAvgScore",
        display_name="计算平均分",
        func_type="object",
        bound_object="Student",
        return_type="REAL",
        params=[ParamDef(name="studentId", param_type="integer")],
        sql_template="""
            SELECT ROUND(AVG(score_value), 1) FROM score WHERE student_id = ?
        """,
        is_derived_property="avgScore",
    ),
    "getCourseAvgScore": FunctionDef(
        api_name="getCourseAvgScore",
        display_name="课程平均分",
        func_type="object",
        bound_object="Course",
        return_type="REAL",
        params=[ParamDef(name="courseId", param_type="integer")],
        sql_template="""
            SELECT ROUND(AVG(score_value), 1) FROM score WHERE course_id = ?
        """,
    ),
    "getPassRate": FunctionDef(
        api_name="getPassRate",
        display_name="课程通过率",
        func_type="object",
        bound_object="Course",
        return_type="TEXT",
        params=[ParamDef(name="courseId", param_type="integer")],
        sql_template="""
            SELECT ROUND(
                COUNT(CASE WHEN score_value >= 60 THEN 1 END) * 100.0 / COUNT(*), 1
            ) || '%'
            FROM score WHERE course_id = ?
        """,
        is_derived_property="passRate",
    ),
    "getAllCourseAvgScores": FunctionDef(
        api_name="getAllCourseAvgScores",
        display_name="所有课程平均分",
        func_type="object_set",
        bound_object="Course",
        return_type="list",
        params=[],
        sql_template="""
            SELECT c.id, c.name, c.semester, ROUND(AVG(sc.score_value), 1) as avg_score,
                   COUNT(sc.id) as student_count
            FROM course c
            LEFT JOIN score sc ON c.id = sc.course_id
            GROUP BY c.id
            ORDER BY c.id
        """,
    ),
    "getTopStudents": FunctionDef(
        api_name="getTopStudents",
        display_name="课程排名",
        func_type="object_set",
        bound_object="Course",
        return_type="list",
        params=[
            ParamDef(name="courseId", param_type="integer"),
            ParamDef(name="limit", param_type="integer", required=False),
        ],
        sql_template="""
            SELECT s.id, s.name, s.age, s.gender, s.class_name, sc.score_value
            FROM score sc
            JOIN student s ON sc.student_id = s.id
            WHERE sc.course_id = ?
            ORDER BY sc.score_value DESC
            LIMIT ?
        """,
    ),
    "validateScore": FunctionDef(
        api_name="validateScore",
        display_name="录入校验",
        func_type="validation",
        bound_object="Score",
        return_type="TEXT",
        params=[
            ParamDef(name="studentId", param_type="integer"),
            ParamDef(name="courseId", param_type="integer"),
            ParamDef(name="scoreValue", param_type="float"),
        ],
        sql_template="",
    ),
    "searchByName": FunctionDef(
        api_name="searchByName",
        display_name="按名称搜索",
        func_type="object_set",
        bound_object="Nameable",
        return_type="list",
        params=[ParamDef(name="keyword", param_type="string", required=False)],
        sql_template="""
            SELECT id, name, 'Student' as _type, 'Student' as result_type FROM student WHERE name LIKE '%' || ? || '%'
            UNION ALL
            SELECT id, name, 'Teacher' as _type, 'Teacher' as result_type FROM teacher WHERE name LIKE '%' || ? || '%'
            UNION ALL
            SELECT id, name, 'Course' as _type, 'Course' as result_type FROM course WHERE name LIKE '%' || ? || '%'
        """,
    ),
    "getScoreSummary": FunctionDef(
        api_name="getScoreSummary",
        display_name="成绩汇总",
        func_type="object",
        bound_object="Scoreable",
        return_type="TEXT",
        params=[
            ParamDef(name="objectType", param_type="string"),
            ParamDef(name="objectId", param_type="integer"),
        ],
        sql_template="",
    ),
}

# ============================================================
# Interfaces
# ============================================================

INTERFACES: dict[str, InterfaceDef] = {
    "Nameable": InterfaceDef(
        api_name="Nameable",
        display_name="可命名对象",
        description="拥有名称属性的对象，可被按名称搜索",
        shared_properties=["name"],
        shared_functions=["searchByName"],
        implementors=["Student", "Teacher", "Course"],
    ),
    "Scoreable": InterfaceDef(
        api_name="Scoreable",
        display_name="可评分对象",
        description="可以拥有成绩记录的对象，支持成绩汇总查询",
        shared_properties=[],
        shared_functions=["getScoreSummary"],
        implementors=["Student", "Course"],
    ),
}

# ============================================================
# Object Sets
# ============================================================

OBJECT_SETS: dict[str, ObjectSetDef] = {
    "TopStudents": ObjectSetDef(
        api_name="TopStudents",
        display_name="优秀学生",
        object_type="Student",
        description="平均分 >= 85 的优秀学生",
        sql="""
            SELECT id FROM student
            WHERE (SELECT ROUND(AVG(score_value), 1) FROM score WHERE student_id = student.id) >= 85
        """,
    ),
    "PassedCourses": ObjectSetDef(
        api_name="PassedCourses",
        display_name="及格课程",
        object_type="Course",
        description="课程平均分 >= 60 的及格课程",
        sql="""
            SELECT id FROM course
            WHERE (SELECT ROUND(AVG(score_value), 1) FROM score WHERE course_id = course.id) >= 60
        """,
    ),
}
