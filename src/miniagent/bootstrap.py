"""组装应用依赖；此模块不创建界面、不读取聊天历史。"""
from miniagent.adapters.llm import select_backend
from miniagent.contracts import ChatDependencies
from miniagent.tools import implementations


def build_chat_dependencies(settings, knowledge_base, logger, runner=None, compressor=None):
    """集中选择后端，UI 与检索层不负责创建模型和工具。"""
    functions = implementations.permitted_functions()
    backend = select_backend(settings, functions)
    if backend is not None:
        return ChatDependencies(knowledge_base, None, None, None, logger, backend)
    from miniagent.adapters import legacy
    agent, _ = legacy.build_legacy_agents()
    return ChatDependencies(knowledge_base, agent, runner or legacy.Runner,
                            compressor or legacy.compress_history, logger)
