"""
知识图谱构建 — 从 knowledge_graph.py 拆分。

当前为门面模式：核心实现仍在 _impl.py (3303行) 中。
后续逐步展开闭包为独立模块。
"""
from ._impl import (
    build_knowledge_graph,
    resolve_knowledge_environment,
    resolve_knowledge_environments_from_text,
)

__all__ = [
    'build_knowledge_graph',
    'resolve_knowledge_environment',
    'resolve_knowledge_environments_from_text',
]
