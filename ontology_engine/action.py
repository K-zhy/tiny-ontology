"""
Action 引擎 — 执行 Ontology Action（校验 -> 事务 -> 审计）。
所有写操作必须通过 Action，不直接操作数据库表。

框架提供通用执行骨架，具体 Action 逻辑由外部通过 register_action_handler 注入。
"""

import json
from typing import Callable
from ontology_engine.database import get_connection
from ontology_engine.registry import ACTION_TYPES

# ---- 自定义 Handler 注册表 ----
# action_name -> handler(conn, params) -> dict
_ACTION_HANDLERS: dict[str, Callable] = {}
# validation_func_name -> validator(params) -> (bool, str)
_VALIDATION_HANDLERS: dict[str, Callable] = {}


def register_action_handler(action_name: str, handler: Callable) -> None:
    """注册自定义 Action 执行逻辑。

    handler 签名: (conn: sqlite3.Connection, params: dict) -> dict
    返回的 dict 会作为 Action 结果（框架自动加 success=True + audited=True）。
    """
    _ACTION_HANDLERS[action_name] = handler


def register_validation_handler(func_name: str, handler: Callable) -> None:
    """注册自定义校验逻辑。

    handler 签名: (params: dict) -> tuple[bool, str]
    返回 (True, "") 表示通过，(False, "错误信息") 表示拒绝。
    """
    _VALIDATION_HANDLERS[func_name] = handler


def execute_action(action_name: str, params: dict, operator: str = "system") -> dict:
    """执行一个 Action，返回结果字典。"""
    action_def = ACTION_TYPES.get(action_name)
    if not action_def:
        return {"success": False, "error": f"Unknown action: {action_name}"}

    # Step 1: 参数校验
    for p in action_def.params:
        if p.required and p.name not in params:
            return {"success": False, "error": f"Missing required param: {p.name}"}

    conn = get_connection()
    try:
        # Step 2: 业务校验（如果定义了 validation_func）
        if action_def.validation_func:
            valid, msg = _run_validation(action_def.validation_func, params)
            if not valid:
                conn.close()
                return {"success": False, "error": msg}

        # Step 3: 事务性执行
        handler = _ACTION_HANDLERS.get(action_name)
        if handler:
            result = handler(conn, params)
        else:
            result = {"message": f"Action '{action_name}' executed (no custom handler)"}

        # Step 4: 审计日志
        conn.execute(
            "INSERT INTO audit_log (action_name, operator, params, result) VALUES (?, ?, ?, ?)",
            (action_name, operator, json.dumps(params, ensure_ascii=False),
             json.dumps(result, ensure_ascii=False))
        )
        conn.commit()
        result["success"] = True
        result["audited"] = True
        return result

    except Exception as e:
        conn.rollback()
        return {"success": False, "error": str(e)}
    finally:
        conn.close()


def _run_validation(func_name: str, params: dict) -> tuple[bool, str]:
    """执行业务校验。优先使用注册的自定义 handler，否则直接通过。"""
    handler = _VALIDATION_HANDLERS.get(func_name)
    if handler:
        return handler(params)
    return True, ""
