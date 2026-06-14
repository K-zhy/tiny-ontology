"""学生成绩 Demo 的 ObjectSet 定义。"""

from ontology_engine.schema import ObjectSetDef


OBJECT_SETS: dict[str, ObjectSetDef] = {
    "TopStudents": ObjectSetDef(
        api_name="TopStudents",
        display_name="优秀学生",
        object_type="Student",
        description="平均分 >= 85 的优秀学生",
        filters={"avgScore": {"op": "gte", "value": 85}},
    ),
    "PassedCourses": ObjectSetDef(
        api_name="PassedCourses",
        display_name="及格课程",
        object_type="Course",
        description="课程平均分 >= 60 的及格课程",
        filters={"passRate": {"op": "gte", "value": 60}},
    ),
    "LongServingEmployees": ObjectSetDef(
        api_name="LongServingEmployees",
        display_name="老员工",
        object_type="Teacher",
        description="教龄超过10年的教师",
        filters={"Tyear": {"op": "gt", "value": 10}},
    ),
}
