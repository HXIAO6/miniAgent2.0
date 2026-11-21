"""组装应用依赖；此模块不创建界面、不读取聊天历史。"""
from miniagent.adapters.llm import select_backend
from miniagent.contracts import ChatDependencies
from miniagent.tools import implementations
from miniagent.runtime import RuntimeEnvironment, bind_environment
from miniagent.security.policy import load_policy


def build_chat_dependencies(settings, knowledge_base, logger, runner=None, compressor=None):
    """集中选择后端，UI 与检索层不负责创建模型和工具。"""
    environment = RuntimeEnvironment(settings, load_policy(str(settings.security_policy_path)))
    with bind_environment(environment):
        functions = implementations.permitted_functions()
        backend = select_backend(settings, functions)
        if backend is not None:
            return ChatDependencies(knowledge_base, None, None, None, logger, backend, environment)
        from miniagent.adapters import legacy
        agent, _ = legacy.build_legacy_agents(settings, functions)
        return ChatDependencies(knowledge_base, agent, runner or legacy.Runner,
                                compressor or legacy.compress_history, logger, environment=environment)


def build_chat_service(settings, knowledge_base, store, operation_lock, executor=None, dependency_factory=None):
    """装配只发生在入口层，应用服务不反向依赖 bootstrap。"""
    from miniagent.application.chat_service import ChatService
    from miniagent.config import logger
    extra = {"executor": executor} if executor is not None else {}
    factory = dependency_factory or (lambda: build_chat_dependencies(settings, knowledge_base, logger))
    return ChatService(settings, knowledge_base, store, operation_lock, dependency_factory=factory, **extra)
