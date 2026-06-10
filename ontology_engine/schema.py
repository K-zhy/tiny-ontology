"""
Ontology Schema 注册表 — 定义 Object/Link/Action/Function 的元数据。
这是 Ontology 语义层的核心：把所有「表/列/外键」翻译为「对象/属性/关系/操作」。
"""

from dataclasses import dataclass, field
from typing import Optional


# ---- Property ----

@dataclass
class PropertyDef:
    """Object Type 的属性定义"""
    name: str           # 业务名称，如 "name", "avgScore"
    prop_type: str      # "primary_key" | "regular" | "derived"
    column: str         # 来源列名（derived 类型可为空）
    data_type: str      # "TEXT" | "INTEGER" | "REAL"


# ---- Object Type ----

@dataclass
class ObjectTypeDef:
    """Object Type 定义"""
    api_name: str               # "Student"
    display_name: str           # "学生"
    table: str                  # 底层数据表
    properties: list[PropertyDef]


# ---- Link Type ----

@dataclass
class LinkTypeDef:
    """Link Type 定义"""
    api_name: str               # "earnedBy"
    display_name: str           # "成绩属于"
    source_type: str            # 源 Object Type（持有 FK 的一方）
    target_type: str            # 目标 Object Type
    cardinality: str            # "many_to_one" | "one_to_many" | "many_to_many"
    reverse_name: str           # 反向遍历时的名称，如 "scores"
    source_fk: Optional[str] = None      # 源表中的 FK 列名
    source_pk: Optional[str] = None      # 源表用于连接的主键列名
    target_pk: Optional[str] = None      # 目标表用于连接的主键列名
    bridge_table: Optional[str] = None   # many_to_many 时的桥表名
    bridge_source_fk: Optional[str] = None   # 桥表中指向 source 的 FK
    bridge_target_fk: Optional[str] = None   # 桥表中指向 target 的 FK


# ---- Action Type ----

@dataclass
class ParamDef:
    name: str
    param_type: str             # "integer" | "string" | "float"
    required: bool = True


@dataclass
class ActionTypeDef:
    """Action Type 定义"""
    api_name: str               # "createScore"
    display_name: str           # "录入成绩"
    action_type: str            # "object" | "link"
    bound_object: str           # 绑定的 Object Type
    params: list[ParamDef]
    validation_func: Optional[str] = None   # 关联的校验 Function 名


# ---- Function ----

@dataclass
class FunctionDef:
    """Function 定义"""
    api_name: str               # "getAvgScore"
    display_name: str           # "计算平均分"
    func_type: str              # "object" | "object_set" | "validation"
    bound_object: str           # 绑定的 Object Type
    return_type: str            # "REAL" | "TEXT" | "INTEGER" | "list"
    params: list[ParamDef]
    sql_template: str           # SQL 模板，用 ? 占位
    is_derived_property: str = ""  # 如果是派生属性，属性名是什么


# ---- Interface ----

@dataclass
class InterfaceDef:
    """Interface 定义 — 跨对象的共享能力契约"""
    api_name: str               # "Nameable"
    display_name: str           # "可命名对象"
    description: str            # 说明
    shared_properties: list[str]  # 共享属性名列表
    shared_functions: list[str]   # 共享 Function 的 api_name
    implementors: list[str]       # 实现该 Interface 的 Object Type api_name


# ---- Object Set ----

@dataclass
class ObjectSetDef:
    """ObjectSet 定义 — 具名、可复用的对象集合"""
    api_name: str               # "TopStudents"
    display_name: str           # "优秀学生"
    object_type: str            # "Student" — 集合中对象的类型
    description: str            # "平均分 >= 85 的学生"
    filters: Optional[dict] = None  # 属性过滤定义（支持与 query_objects_v2 一致的过滤语法）
    sql: str = ""                 # 兼容旧定义：SQL 查询，返回主键列表，列别名应为 object_id
