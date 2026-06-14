"""学生成绩 Demo 的 Action Type 定义。"""

from ontology_engine.schema import ActionTypeDef, ParamDef


ACTION_TYPES: dict[str, ActionTypeDef] = {
    "createScore": ActionTypeDef(
        api_name="createScore",
        display_name="录入成绩",
        action_type="object",
        bound_object="Score",
        params=[
            ParamDef(name="studentSno", param_type="string"),
            ParamDef(name="courseCno", param_type="string"),
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
        params=[ParamDef(name="scoreId", param_type="integer")],
    ),
    "assignTeacher": ActionTypeDef(
        api_name="assignTeacher",
        display_name="分配教师",
        action_type="link",
        bound_object="Course",
        params=[
            ParamDef(name="courseCno", param_type="string"),
            ParamDef(name="teacherTno", param_type="string"),
            ParamDef(name="semester", param_type="string", required=False),
        ],
    ),
}
