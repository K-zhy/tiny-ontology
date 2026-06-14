"""学生成绩 Demo 的 Link Type 定义。"""

from ontology_engine.schema import LinkTypeDef


LINK_TYPES: dict[str, LinkTypeDef] = {
    "course": LinkTypeDef(
        api_name="course",
        display_name="所属课程",
        source_type="TeachingAssignment",
        target_type="Course",
        source_fk="Cno",
        reverse_name="teachingAssignments",
    ),
    "teacher": LinkTypeDef(
        api_name="teacher",
        display_name="授课教师",
        source_type="TeachingAssignment",
        target_type="Teacher",
        source_fk="Tno",
        reverse_name="teachingAssignments",
    ),
    "earnedBy": LinkTypeDef(
        api_name="earnedBy",
        display_name="成绩属于",
        source_type="Score",
        target_type="Student",
        source_fk="Sno",
        reverse_name="scores",
    ),
    "forCourse": LinkTypeDef(
        api_name="forCourse",
        display_name="成绩对应课程",
        source_type="Score",
        target_type="Course",
        source_fk="Cno",
        reverse_name="scores",
    ),
}
