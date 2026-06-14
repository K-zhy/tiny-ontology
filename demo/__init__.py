"""
学生成绩管理 Demo — 示例 Ontology 定义
=======================================
这是 OAG 框架的一个使用示例。
想要接入新数据库/新对象定义时，照此格式创建一套新的 demo 目录即可。

文件说明：
  demo/
    __init__.py        ← 启动入口：load() 注册自定义 handler
    registry.py        ← Ontology 六要素定义（Student/Teacher/Course/Score）
    handlers.py        ← 自定义 Action/Function 业务逻辑
    config.py          ← OAG 领域配置（OntologyConfig + Score 富化）

使用方式（在 server.py 或 main 中）：
  import demo
  demo.load()   # 注册 Action/Function handler
"""

def load() -> None:
    """注册学生成绩 Demo 的自定义 handler。"""
    from .handlers import register_all_handlers

    register_all_handlers()
