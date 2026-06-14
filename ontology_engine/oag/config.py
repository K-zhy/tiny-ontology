"""OntologyConfig — 领域专属配置，作为通用框架与具体业务的唯一接触点。

框架层（pipeline / tool_registry / system_tools / capabilities）对具体业务一无所知。
所有领域知识都封装在 OntologyConfig 实例中，由调用方（如 nl_oag.py）传入。

典型用法：
    from ontology_engine.oag.config import OntologyConfig

    config = OntologyConfig(
        type_aliases={"学生": "Student", ...},
        extra_type_keywords={"Student": ["同学", "学号"], ...},
        value_aliases={"gender": {"男": "M", ...}},
        result_enricher=my_enrich_fn,
        type_expansion_rules={"Score": ["Student", "Course"]},
        system_prompt_addendum="Score 查询结果会自动补充 studentName...",
    )
    pipeline = OAGPipeline(registry, llm_fn, config=config)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class OntologyConfig:
    """领域专属配置载体。字段均可选，不提供时框架使用无损默认行为。"""

    # ---- 对象类型别名 ----
    # 中文/别称 → Object Type api_name
    # 例：{"学生": "Student", "教师": "Teacher"}
    type_aliases: dict[str, str] = field(default_factory=dict)

    # ---- 字段值别名 ----
    # 属性名 → {原始值 → 规范值}
    # 例：{"gender": {"男": "M", "女": "F"}}
    value_aliases: dict[str, dict[str, str]] = field(default_factory=dict)

    # ---- 额外推断关键词 ----
    # Object Type api_name → 领域专用词列表（补充 registry display_name 的自动派生）
    # 例：{"Student": ["同学", "学号", "平均分"]}
    extra_type_keywords: dict[str, list[str]] = field(default_factory=dict)

    # ---- 类型扩展规则 ----
    # 当某个类型被推断到时，自动扩展关联类型（用于解决隐式依赖）
    # 例：{"Score": ["Student", "Course"]} 表示查 Score 时总需要 Student 和 Course 的名称富化
    type_expansion_rules: dict[str, list[str]] = field(default_factory=dict)

    # ---- 查询结果后处理钩子 ----
    # 签名：(results: list[dict]) -> None（原地修改）
    # 用于领域专属的结果富化（如为 Score 补充 studentName/courseName）
    result_enricher: Callable[[list[dict]], None] | None = None

    # ---- System Prompt 补充 ----
    # 追加在通用 System Prompt 之后的领域专属约束说明
    # 例："Score 查询结果会自动补充 studentName、courseName、teacherName，不要再重复查询..."
    system_prompt_addendum: str = ""


# ---- 空配置单例（框架默认值）----
DEFAULT_CONFIG = OntologyConfig()
