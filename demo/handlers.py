"""学生成绩 Demo 的 handler 注册出口。"""

from .action_handlers import register_action_handlers
from .function_handlers import register_function_handlers
from .validation_handlers import register_validation_handlers


def register_all_handlers() -> None:
    """注册本 demo 所有自定义 Action、Validation 和 Function handler。"""
    register_action_handlers()
    register_validation_handlers()
    register_function_handlers()
