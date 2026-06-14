"""OAG 共享工具函数：过滤条件规范化（纯工具，无领域知识）。

领域专属内容（类型别名、值别名、结果富化）由 OntologyConfig 传入，
框架本身不感知任何具体业务。
"""
from __future__ import annotations


# ---- 过滤条件规范化 ----

def normalize_filter_value(prop_name: str, value, value_aliases: dict | None = None):
    """规范化单个过滤值。value_aliases 由 OntologyConfig 提供，不在此处硬编码。"""
    if isinstance(value, str):
        alias_map = (value_aliases or {}).get(prop_name)
        if alias_map:
            return alias_map.get(value.lower(), alias_map.get(value, value))
        return value
    if isinstance(value, list):
        return [normalize_filter_value(prop_name, item, value_aliases) for item in value]
    if isinstance(value, dict):
        return {
            k: normalize_filter_value(prop_name, v, value_aliases) if k == "value" else v
            for k, v in value.items()
        }
    return value


def normalize_filters(filters: dict, value_aliases: dict | None = None) -> dict:
    """规范化过滤条件字典。value_aliases 由 OntologyConfig 提供。"""
    normalized = {}
    for key, value in filters.items():
        if key == "$or" and isinstance(value, list):
            normalized[key] = [
                normalize_filters(item, value_aliases) if isinstance(item, dict) else item
                for item in value
            ]
            continue
        prop_name = key.split(".")[-1]
        normalized[key] = normalize_filter_value(prop_name, value, value_aliases)
    return normalized


# 结果富化：框架不提供默认实现，由 OntologyConfig.result_enricher 注入。
# 参见 nl_oag.py 中 _enrich_score_context() 作为示例。
