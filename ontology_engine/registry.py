"""当前 Demo 的 Ontology 定义导出层。

框架模块通过这里读取 Object/Link/Action/Function 等定义；定义来源是
``demo.registry`` 的显式导入，不再使用运行时全局注册。
"""

from demo.registry import (
    ACTION_TYPES,
    DEMO_REGISTRY,
    FUNCTIONS,
    INTERFACES,
    LINK_TYPES,
    OBJECT_SETS,
    OBJECT_TYPES,
)

__all__ = [
    "OBJECT_TYPES",
    "LINK_TYPES",
    "ACTION_TYPES",
    "FUNCTIONS",
    "INTERFACES",
    "OBJECT_SETS",
    "DEMO_REGISTRY",
]
