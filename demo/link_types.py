"""学生成绩 Demo 的 Link Type 定义。"""

from ontology_engine.schema import LinkTypeDef


LINK_TYPES: dict[str, LinkTypeDef] = {
    "course": LinkTypeDef(
        api_name="course",
        display_name="所属课程",
        source_type="TeachingAssignment",
        target_type="Course",
        cardinality="many_to_one",
        source_fk="Cno",
        reverse_name="teachingAssignments",
        source_pk="id",
        target_pk="Cno",
    ),
    "teacher": LinkTypeDef(
        api_name="teacher",
        display_name="授课教师",
        source_type="TeachingAssignment",
        target_type="Teacher",
        cardinality="many_to_one",
        source_fk="Tno",
        reverse_name="teachingAssignments",
        source_pk="id",
        target_pk="Tno",
    ),
    "earnedBy": LinkTypeDef(
        api_name="earnedBy",
        display_name="成绩属于",
        source_type="Score",
        target_type="Student",
        cardinality="many_to_one",
        source_fk="Sno",
        reverse_name="scores",
        source_pk="id",
        target_pk="Sno",
    ),
    "forCourse": LinkTypeDef(
        api_name="forCourse",
        display_name="成绩对应课程",
        source_type="Score",
        target_type="Course",
        cardinality="many_to_one",
        source_fk="Cno",
        reverse_name="scores",
        source_pk="id",
        target_pk="Cno",
    ),
    "taughtBy": LinkTypeDef(
        api_name="taughtBy",
        display_name="授课教师（兼容直连）",
        source_type="Course",
        target_type="Teacher",
        cardinality="many_to_many",
        reverse_name="courses",
        source_pk="Cno",
        target_pk="Tno",
        bridge_table="tc",
        bridge_source_fk="Cno",
        bridge_target_fk="Tno",
    ),
}
