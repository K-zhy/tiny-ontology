"""学生成绩 Demo 的 Function 定义。"""

from ontology_engine.schema import FunctionDef, ParamDef


FUNCTIONS: dict[str, FunctionDef] = {
    "getAvgScore": FunctionDef(
        api_name="getAvgScore",
        display_name="计算平均分",
        func_type="object",
        bound_object="Student",
        return_type="REAL",
        params=[ParamDef(name="studentSno", param_type="string")],
        sql_template="SELECT ROUND(AVG(score_value), 1) FROM score WHERE Sno = ?",
        is_derived_property="avgScore",
    ),
    "getCourseAvgScore": FunctionDef(
        api_name="getCourseAvgScore",
        display_name="课程平均分",
        func_type="object",
        bound_object="Course",
        return_type="REAL",
        params=[ParamDef(name="courseCno", param_type="string")],
        sql_template="SELECT ROUND(AVG(score_value), 1) FROM score WHERE Cno = ?",
    ),
    "getPassRate": FunctionDef(
        api_name="getPassRate",
        display_name="课程通过率",
        func_type="object",
        bound_object="Course",
        return_type="TEXT",
        params=[ParamDef(name="courseCno", param_type="string")],
        sql_template="""
            SELECT ROUND(
                COUNT(CASE WHEN score_value >= 60 THEN 1 END) * 100.0 / COUNT(*), 1
            ) || '%' FROM score WHERE Cno = ?
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
            SELECT c.Cno, c.name, COALESCE(GROUP_CONCAT(DISTINCT tc.semester), '') as semester,
                   ROUND(AVG(sc.score_value), 1) as avg_score, COUNT(sc.id) as student_count
            FROM course c LEFT JOIN score sc ON c.Cno = sc.Cno LEFT JOIN tc ON c.Cno = tc.Cno
            GROUP BY c.Cno ORDER BY c.Cno
        """,
    ),
    "getTopStudents": FunctionDef(
        api_name="getTopStudents",
        display_name="课程排名",
        func_type="object_set",
        bound_object="Course",
        return_type="list",
        params=[
            ParamDef(name="courseCno", param_type="string"),
            ParamDef(name="limit", param_type="integer", required=False),
        ],
        sql_template="""
            SELECT s.Sno, s.name, s.age, s.gender, s.class_name, s.Sbirthday, sc.score_value
            FROM score sc JOIN student s ON sc.Sno = s.Sno WHERE sc.Cno = ?
            ORDER BY sc.score_value DESC LIMIT ?
        """,
    ),
    "validateScore": FunctionDef(
        api_name="validateScore",
        display_name="录入校验",
        func_type="validation",
        bound_object="Score",
        return_type="TEXT",
        params=[
            ParamDef(name="studentSno", param_type="string"),
            ParamDef(name="courseCno", param_type="string"),
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
            SELECT Sno as object_id, name, 'Student' as _type, 'Student' as result_type FROM student WHERE name LIKE '%' || ? || '%'
            UNION ALL
            SELECT Tno as object_id, name, 'Teacher' as _type, 'Teacher' as result_type FROM teacher WHERE name LIKE '%' || ? || '%'
            UNION ALL
            SELECT Cno as object_id, name, 'Course' as _type, 'Course' as result_type FROM course WHERE name LIKE '%' || ? || '%'
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
            ParamDef(name="objectId", param_type="string"),
        ],
        sql_template="",
    ),
}
