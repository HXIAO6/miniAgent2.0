"""工作流状态只保存本轮请求与结束状态，数据库和模型实例通过闭包注入。"""
from typing import TypedDict
from miniagent.contracts import ChatRequest


class ChatState(TypedDict, total=False):
    request: ChatRequest
    route: str
    completed: bool
