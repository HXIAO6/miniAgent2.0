"""聊天服务的输入与事件契约，不依赖 Gradio 或特定模型 SDK。"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ChatRequest:
    """单次请求；第一阶段保持原有检索参数和默认行为。"""

    message: str
    history: list = field(default_factory=list)
    use_knowledge: bool = True
    top_k: int = 4
    candidate_k: int = 20
    retrieval_mode: str = "hybrid"
    use_rerank: bool = True
    rerank_threshold: float = 0.2
    rerank_k: int = 20
    only_knowledge: bool = True


@dataclass(frozen=True)
class ChatEvent:
    """一次状态快照；界面自行将原文、引用和状态渲染成 HTML。"""

    kind: str
    history: list[dict]
    answer: str = ""
    status: str = ""
    elapsed_seconds: float = 0
    expanded: bool = False
    candidates: list[dict] = field(default_factory=list)
    selected: list[dict] = field(default_factory=list)
    update_scores: bool = False
    persist: bool = False


@dataclass(frozen=True)
class ChatDependencies:
    """由入口注入检索、旧 SDK 和可选新后端，测试可替换为离线实现。"""

    knowledge_base: object
    agent: object
    runner: object
    compress_history: object
    logger: object
    # 未指定时运行原 SDK；由界面入口显式选择新适配器，旧测试与调用方式继续兼容。
    backend: object = None


@dataclass(frozen=True)
class ModelEvent:
    """模型适配器输出的增量，避免把 LangChain 内部对象传给界面。"""

    kind: str
    text: str
