from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FeedbackClass(str, Enum):
    RESPONSE_ANOMALY = "response_anomaly"
    ACTION_EXECUTION_FAILURE = "action_execution_failure"
    ACTION_EXECUTION_SUCCESS = "action_execution_success"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ActionExecutionFeedback:
    role_id: str
    succeeded: bool

    @property
    def classification(self) -> FeedbackClass:
        return (
            FeedbackClass.ACTION_EXECUTION_SUCCESS
            if self.succeeded
            else FeedbackClass.ACTION_EXECUTION_FAILURE
        )


def classify_role_action_result(value: bool | None) -> FeedbackClass:
    if value is True:
        return FeedbackClass.ACTION_EXECUTION_SUCCESS
    if value is False:
        return FeedbackClass.ACTION_EXECUTION_FAILURE
    return FeedbackClass.UNKNOWN


def is_request_timeout_description(description: str) -> bool:
    """判断收到的 server error 是否明确表示玩家请求响应超时。

    这里只分析**协议中实际收到的 ``server_errors[].description``**，不读取最终
    下载日志或判题器额外打印的 System prompt。之所以不只看 errorCode，是因为
    不同赛段/接口版本对数值编码可能存在差异，而 ``request timeout`` 文本已经是
    当前响应携带的权威语义。
    """

    text = str(description).strip().casefold()
    return (
        "request timeout" in text
        or ("[timeout]" in text and "player" in text)
    )


def has_request_timeout(server_errors) -> bool:
    """一组 server_errors 中是否存在明确的上一请求超时反馈。"""

    return any(
        is_request_timeout_description(
            getattr(error, "description", "")
        )
        for error in server_errors
    )
