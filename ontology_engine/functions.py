"""
Function 引擎 — 执行 Ontology Function。
所有 Function 定义在 registry 中，默认按 sql_template 执行。
需要自定义逻辑的 Function 可通过 register_function_handler 注入。
"""

from typing import Optional, Callable
from ontology_engine.database import get_connection
from ontology_engine.registry import FUNCTIONS

# ---- 自定义 Handler 注册表 ----
# func_name -> handler(params: dict) -> dict
_FUNCTION_HANDLERS: dict[str, Callable] = {}


def register_function_handler(func_name: str, handler: Callable) -> None:
    """注册自定义 Function 执行逻辑。

    handler 签名: (params: dict) -> dict
    返回 {"success": True, "data": ...} 或 {"success": False, "error": ...}
    注册后该 Function 不再走默认的 sql_template 执行路径。
    """
    _FUNCTION_HANDLERS[func_name] = handler


def call_function(func_name: str, params: Optional[dict] = None) -> dict:
    """调用一个 Function。

    执行优先级：
    1. 如果有注册的自定义 handler → 直接调用
    2. 否则按 func_def.sql_template 执行 SQL
    """
    params = params or {}
    func_def = FUNCTIONS.get(func_name)
    if not func_def:
        return {"success": False, "error": f"Unknown function: {func_name}"}

    # 优先使用自定义 handler
    custom_handler = _FUNCTION_HANDLERS.get(func_name)
    if custom_handler:
        return custom_handler(params)

    # 默认路径：按 sql_template 执行
    if not func_def.sql_template or not func_def.sql_template.strip():
        return {"success": False, "error": f"Function '{func_name}' has no sql_template and no custom handler"}

    # 填充参数（按定义顺序）
    sql_params = []
    for p in func_def.params:
        val = params.get(p.name)
        if val is None and p.required:
            return {"success": False, "error": f"Missing param: {p.name}"}
        sql_params.append(val)

    conn = get_connection()
    try:
        if func_def.func_type == "object_set":
            # 批量 Function：返回多行
            rows = conn.execute(func_def.sql_template.strip(), sql_params).fetchall()
            results = [dict(row) for row in rows]
            conn.close()
            return {"success": True, "data": results}

        if func_def.func_type == "validation":
            conn.close()
            # validation 类型没有自定义 handler 时返回通过
            return {"success": True, "data": {"valid": True, "message": "ok"}}

        # 标量 Function（getAvgScore, getCourseAvgScore, getPassRate 等）
        row = conn.execute(func_def.sql_template.strip(), sql_params).fetchone()
        conn.close()
        val = row[0] if row else None
        return {"success": True, "data": val}
    except Exception as e:
        conn.close()
        return {"success": False, "error": str(e)}


def compute_derived_property(object_type: str, object_id, prop_name: str):
    """计算单个对象的派生属性。"""
    for func_def in FUNCTIONS.values():
        if (func_def.is_derived_property == prop_name
                and func_def.bound_object == object_type):
            result = call_function(func_def.api_name,
                                  {func_def.params[0].name: object_id})
            if result.get("success"):
                return result["data"]
    return None
