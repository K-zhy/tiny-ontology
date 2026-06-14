"""学生成绩 Demo 的 Interface 定义。"""

from ontology_engine.schema import InterfaceDef


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
