"""Supervisor Prompt 测试"""

import pytest
from src.agents.prompts.supervisor_prompt import (
    SUPERVISOR_SYSTEM_PROMPT,
    THINK_TEMPLATE,
    PLAN_TEMPLATE,
    OBSERVE_TEMPLATE,
    REFLECT_TEMPLATE,
)


def test_supervisor_prompt_not_empty():
    """验证 Supervisor Prompt 不为空"""
    assert SUPERVISOR_SYSTEM_PROMPT is not None
    assert len(SUPERVISOR_SYSTEM_PROMPT) > 0


def test_think_template_renders():
    """验证 Think 模板可渲染"""
    rendered = THINK_TEMPLATE.format(
        user_query="000001",
        current_iteration=1,
        max_iterations=10,
        existing_results="无",
        pending_tasks="无",
    )
    assert "[Think]" in rendered
    assert "000001" in rendered


def test_plan_template_renders():
    """验证 Plan 模板可渲染"""
    rendered = PLAN_TEMPLATE.format(intent_type="STOCK_ANALYSIS")
    assert "[Plan]" in rendered
    assert "STOCK_ANALYSIS" in rendered


def test_observe_template_renders():
    """验证 Observe 模板可渲染"""
    rendered = OBSERVE_TEMPLATE.format(agent_results="{}")
    assert "[Observe]" in rendered


def test_reflect_template_renders():
    """验证 Reflect 模板可渲染"""
    rendered = REFLECT_TEMPLATE.format(
        assessment="所有结果已收集",
        quality_issues="无",
        missing_analysis="无",
    )
    assert "[Reflect]" in rendered