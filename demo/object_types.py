"""学生成绩 Demo 的 Object Type 定义。"""

from ontology_engine.schema import ObjectTypeDef, PropertyDef


OBJECT_TYPES: dict[str, ObjectTypeDef] = {
    "Student": ObjectTypeDef(
        api_name="Student",
        display_name="学生",
        table="student",
        properties=[
            PropertyDef(name="Sno", prop_type="primary_key", column="Sno", data_type="TEXT"),
            PropertyDef(name="id", prop_type="regular", column="id", data_type="INTEGER"),
            PropertyDef(name="name", prop_type="regular", column="name", data_type="TEXT"),
            PropertyDef(name="age", prop_type="regular", column="age", data_type="INTEGER"),
            PropertyDef(name="gender", prop_type="regular", column="gender", data_type="TEXT"),
            PropertyDef(name="className", prop_type="regular", column="class_name", data_type="TEXT"),
            PropertyDef(name="Sbirthday", prop_type="regular", column="Sbirthday", data_type="TEXT"),
            PropertyDef(name="avgScore", prop_type="derived", column="", data_type="REAL"),
        ],
    ),
    "Teacher": ObjectTypeDef(
        api_name="Teacher",
        display_name="教师",
        table="teacher",
        properties=[
            PropertyDef(name="Tno", prop_type="primary_key", column="Tno", data_type="TEXT"),
            PropertyDef(name="id", prop_type="regular", column="id", data_type="INTEGER"),
            PropertyDef(name="name", prop_type="regular", column="name", data_type="TEXT"),
            PropertyDef(name="subject", prop_type="regular", column="subject", data_type="TEXT"),
            PropertyDef(name="department", prop_type="regular", column="department", data_type="TEXT"),
            PropertyDef(name="Tsex", prop_type="regular", column="Tsex", data_type="TEXT"),
            PropertyDef(name="Prof", prop_type="regular", column="Prof", data_type="TEXT"),
            PropertyDef(name="Tyear", prop_type="regular", column="Tyear", data_type="INTEGER"),
        ],
    ),
    "Course": ObjectTypeDef(
        api_name="Course",
        display_name="课程",
        table="course",
        properties=[
            PropertyDef(name="Cno", prop_type="primary_key", column="Cno", data_type="TEXT"),
            PropertyDef(name="id", prop_type="regular", column="id", data_type="INTEGER"),
            PropertyDef(name="name", prop_type="regular", column="name", data_type="TEXT"),
            PropertyDef(name="credit", prop_type="regular", column="credit", data_type="INTEGER"),
            PropertyDef(name="passRate", prop_type="derived", column="", data_type="TEXT"),
        ],
    ),
    "TeachingAssignment": ObjectTypeDef(
        api_name="TeachingAssignment",
        display_name="授课安排",
        table="tc",
        properties=[
            PropertyDef(name="id", prop_type="primary_key", column="id", data_type="INTEGER"),
            PropertyDef(name="courseCno", prop_type="regular", column="Cno", data_type="TEXT"),
            PropertyDef(name="teacherTno", prop_type="regular", column="Tno", data_type="TEXT"),
            PropertyDef(name="semester", prop_type="regular", column="semester", data_type="TEXT"),
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
