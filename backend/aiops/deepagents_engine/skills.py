"""
Skill 加载模块 — 从 AIOpsSkill 模型加载启用的 Skills，供 system prompt 注入。

复用 services.py 中的：
- _get_selected_skills(config, user)  → load_active_skills()
- _skills_for_action(active_skills, action) → 内置过滤逻辑
- _build_skill_trace() → build_skill_trace()
"""

from __future__ import annotations

import logging
from typing import Optional

from django.db import close_old_connections

logger = logging.getLogger(__name__)

ANSWER_FORMATTER_SKILL_SLUG = 'answer-formatter'


def _normalize_json_id_list(values) -> list[int]:
    """将 JSON 列表转为 int 列表，过滤无效值。"""
    normalized = []
    for value in values or []:
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            continue
    return normalized


def load_active_skills(
    config=None,
    action_code: Optional[str] = None,
    user=None,
) -> list[dict]:
    """加载当前会话启用的 Skills，返回标准化 dict 列表。

    过滤规则（对齐 legacy _get_selected_skills + _skills_for_action）：
    1. 从 DB 查询 is_enabled=True 的 Skills
    2. 如果 config.enabled_skill_ids 非空，只加载选中的 ID
    3. 按 skill.allowed_role_codes 过滤无权限用户
    4. 如果传入 action_code，按 skill.applicable_actions 二次过滤
    5. answer-formatter 始终追加

    Returns:
        [{'id':..., 'name':..., 'slug':..., 'category':..., 'description':...,
          'content':..., 'tools':[...], 'output_contract':{...}, 'risk_level':...}, ...]
    """
    close_old_connections()

    try:
        from aiops.models import AIOpsSkill
    except ImportError:
        logger.warning("无法导入 AIOpsSkill 模型")
        return []

    # 1. 基础查询
    queryset = AIOpsSkill.objects.filter(is_enabled=True)

    # 2. 按配置过滤
    if config is not None:
        selected_ids = _normalize_json_id_list(
            getattr(config, 'enabled_skill_ids', None) or []
        )
        if selected_ids:
            queryset = queryset.filter(id__in=selected_ids)

    skills = list(queryset.order_by('is_builtin', 'name', 'id'))

    # 3. RBAC 角色过滤
    if user is not None:
        try:
            role_codes = set(user.rbac_roles.values_list('code', flat=True))
        except Exception:
            role_codes = set()
        filtered = []
        for skill in skills:
            allowed_codes = set(skill.allowed_role_codes or [])
            if allowed_codes and not (allowed_codes & role_codes):
                continue
            filtered.append(skill)
        skills = filtered

    # 4. 按 action_code 过滤 (对齐 _skills_for_action)
    if action_code:
        formatter_skill = None
        action_filtered = []
        for skill in skills:
            if skill.slug == ANSWER_FORMATTER_SKILL_SLUG:
                formatter_skill = skill
                continue
            applicable_actions = set(skill.applicable_actions or [])
            if action_code in applicable_actions:
                action_filtered.append(skill)
        # answer-formatter 始终追加
        if formatter_skill:
            action_filtered.append(formatter_skill)
        skills = action_filtered or skills  # 如果过滤后为空，使用全部

    # 5. 序列化为 dict
    result = []
    for skill in skills:
        result.append({
            'id': skill.id,
            'name': skill.name,
            'slug': skill.slug,
            'category': skill.category or '未分类',
            'description': skill.description or '',
            'content': skill.content or '',
            'tools': list(dict.fromkeys([
                *(skill.builtin_tools or []),
                *(skill.recommended_tools or []),
            ])),
            'output_contract': skill.output_contract or {},
            'risk_level': skill.risk_level or 'read_only',
            'is_builtin': skill.is_builtin,
        })

    logger.debug("加载 %d 个活跃 Skill (action=%s)", len(result), action_code or 'any')
    return result


def build_skill_trace(
    active_skills: list[dict],
    action_code: str = '',
    tool_calls: list[str] | None = None,
    formatter_used: bool = False,
    formatter_fell_back: bool = False,
) -> list[dict]:
    """构建 skill_trace，写入 assistant_message.metadata。

    对齐 legacy _build_skill_trace() (services.py line 2661)。

    Args:
        active_skills: load_active_skills() 的返回值
        action_code: 当前 action code
        tool_calls: 实际调用的工具名称列表
        formatter_used: answer-formatter 是否被使用
        formatter_fell_back: answer-formatter 是否回退

    Returns:
        [{'id':..., 'slug':..., 'name':..., 'status':..., 'hit_reason':...,
          'declared_tools':[...], 'used_tools':[...]}, ...]
    """
    tool_calls = [str(t or '').strip() for t in (tool_calls or []) if str(t or '').strip()]
    items = []

    for skill in active_skills:
        skill_slug = skill.get('slug', '')
        declared_tools = skill.get('tools', [])
        used_tools = [t for t in tool_calls if t in declared_tools]

        status = 'available'
        hit_reason = 'runtime_enabled'

        if action_code and action_code in (skill.get('applicable_actions') or []):
            status = 'matched'
            hit_reason = 'action_router'
        elif used_tools and status == 'available':
            status = 'matched'
            hit_reason = 'tool_dependency'

        if skill_slug == ANSWER_FORMATTER_SKILL_SLUG:
            if formatter_used and formatter_fell_back:
                status = 'fallback'
                hit_reason = 'formatter_fallback'
            elif formatter_used:
                status = 'called'
                hit_reason = 'answer_formatter'
            elif status == 'available':
                hit_reason = 'formatter_available'

        items.append({
            'id': skill.get('id'),
            'slug': skill_slug,
            'name': skill.get('name', ''),
            'status': status,
            'hit_reason': hit_reason,
            'declared_tools': declared_tools,
            'used_tools': used_tools,
        })

    return items


def build_skills_prompt_section(active_skills: list[dict]) -> str:
    """构建 System Prompt 中的「启用 Skill」段落。

    对齐 legacy _build_runtime_prompt() 中 skill_lines 的格式
    (services.py line 15323-15330)。
    """
    if not active_skills:
        return '- 当前无启用 Skill'

    lines = []
    for skill in active_skills:
        name = skill.get('name', '')
        category = skill.get('category', '未分类')
        description = skill.get('description', '')
        applicable = '、'.join(skill.get('applicable_actions', []) or []) or '通用'
        tools = '、'.join(skill.get('tools', [])) or '未声明工具依赖'
        content = skill.get('content', '')

        lines.append(
            f"- {name}（{category}）：{description}\n"
            f"  适用 Action：{applicable}\n"
            f"  工具依赖：{tools}；最终可用工具还要经过 MCP 可用性、用户 RBAC 和 Action 安全策略过滤。\n"
            f"  内容：{content}"
        )

    return '\n'.join(lines)
