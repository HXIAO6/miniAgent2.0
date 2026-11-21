"""请求级运行环境：入口显式绑定，异步任务和检索线程隔离，兼容命令行默认调用。"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from miniagent.config import settings

_environment = ContextVar("miniagent_environment", default=None)


@dataclass(frozen=True)
class RuntimeEnvironment:
    """只携带配置和服务端策略，不接受浏览器提供的权限覆盖。"""

    config: object
    policy: object = None


def current_config(default=None):
    environment = _environment.get()
    return environment.config if environment is not None else (default if default is not None else settings)


def current_policy():
    environment = _environment.get()
    return environment.policy if environment is not None else None


@contextmanager
def bind_environment(environment):
    """只在当前任务绑定，退出后还原；不改模块全局变量。"""
    token = _environment.set(environment)
    try:
        yield
    finally:
        _environment.reset(token)


async def scoped_events(events, environment):
    """逐次拉取时绑定环境，不跨 yield 留下上下文，支持消费者提前结束。"""
    iterator = events.__aiter__()
    try:
        while True:
            with bind_environment(environment):
                try:
                    event = await anext(iterator)
                except StopAsyncIteration:
                    return
            yield event
    finally:
        with bind_environment(environment):
            await iterator.aclose()
