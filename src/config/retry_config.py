"""
重试配置模块

定义任务执行的重试策略、熔断机制和质量阈值。
"""

from typing import Tuple, Dict, Any

# 重试配置
RETRY_CONFIG = {
    "max_retries": 3,               # 最大重试次数
    "retry_delay": 2,                # 重试延迟（秒）
    "timeout": 30,                   # 单次任务超时（秒）
    "circuit_breaker": 5,            # 连续失败5次后熔断
}

# 质量阈值
QUALITY_THRESHOLDS = {
    "min_confidence": 0.5,           # 最低置信度
    "min_data_quality": 0.3,         # 最低数据质量分数
    "max_missing_ratio": 0.3,        # 最大缺失数据比例
}

# 执行控制
EXECUTION_CONFIG = {
    "max_iterations": 10,            # 最大迭代次数
    "parallel_agent_limit": 6,       # 最大并行 Agent 数
    "task_timeout": 60,              # 任务总超时（秒）
}


def should_retry(task: "Task", retry_config: dict = None) -> bool:
    """
    判断任务是否应该重试

    Args:
        task: 任务对象
        retry_config: 重试配置，默认使用 RETRY_CONFIG

    Returns:
        True 如果还可以重试
    """
    if retry_config is None:
        retry_config = RETRY_CONFIG

    max_retries = retry_config.get("max_retries", 3)
    return task.retry_count < max_retries


def is_circuit_broken(failed_count: int, retry_config: dict = None) -> bool:
    """
    判断是否触发熔断

    Args:
        failed_count: 连续失败次数
        retry_config: 重试配置，默认使用 RETRY_CONFIG

    Returns:
        True 如果触发熔断
    """
    if retry_config is None:
        retry_config = RETRY_CONFIG

    circuit_breaker = retry_config.get("circuit_breaker", 5)
    return failed_count >= circuit_breaker


def check_quality_threshold(
    confidence: float,
    data_quality_score: float,
    missing_ratio: float,
) -> Tuple[bool, str]:
    """
    检查是否达到质量阈值

    Args:
        confidence: 置信度
        data_quality_score: 数据质量分数
        missing_ratio: 缺失数据比例

    Returns:
        (是否达标, 原因描述)
    """
    if confidence < QUALITY_THRESHOLDS["min_confidence"]:
        return False, f"置信度 {confidence:.2f} 低于阈值 {QUALITY_THRESHOLDS['min_confidence']}"

    if data_quality_score < QUALITY_THRESHOLDS["min_data_quality"]:
        return False, f"数据质量 {data_quality_score:.2f} 低于阈值 {QUALITY_THRESHOLDS['min_data_quality']}"

    if missing_ratio > QUALITY_THRESHOLDS["max_missing_ratio"]:
        return False, f"缺失比例 {missing_ratio:.2f} 超过阈值 {QUALITY_THRESHOLDS['max_missing_ratio']}"

    return True, "质量达标"
