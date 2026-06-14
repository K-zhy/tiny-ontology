"""学生成绩 Demo 的 Ontology 定义聚合出口。

具体定义按 Ontology 元素类型拆在相邻模块中；这里只负责聚合导出。
"""

from .action_types import ACTION_TYPES
from .function_types import FUNCTIONS
from .interfaces import INTERFACES
from .link_types import LINK_TYPES
from .object_sets import OBJECT_SETS
from .object_types import OBJECT_TYPES


DEMO_REGISTRY = {
    "object_types": OBJECT_TYPES,
    "link_types": LINK_TYPES,
    "action_types": ACTION_TYPES,
    "functions": FUNCTIONS,
    "interfaces": INTERFACES,
    "object_sets": OBJECT_SETS,
}
