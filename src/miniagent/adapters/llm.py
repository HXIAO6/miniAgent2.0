"""LangChain 模型适配：沿用原服务，输出稳定事件，不操作知识库或聊天数据库。"""
from pathlib import Path

from miniagent.contracts import ModelEvent

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
STRICT_INSTRUCTIONS = (
    "\n本轮为仅依据知识库模式，只能使用本轮参考资料回答；历史聊天不作为事实证据。"
    "不使用常识补全缺失信息，明确指出资料不足的部分。"
)


def load_prompt(name):
    """只加载程序指定的 Prompt 文件，用户输入不参与路径选择。"""
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8").strip()


def content_text(content):
    """兼容字符串和 LangChain 文本块；不将工具参数或未知块混入回答。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(block.get("text", "") for block in content
                       if isinstance(block, dict) and block.get("type") == "text")
    return ""


def build_model(settings, model_name):
    """显式传入现有地址与密钥；不依赖全局 OpenAI 客户端或切换模型服务。"""
    from langchain_openai import ChatOpenAI
    if not settings.openai_api_key or not settings.openai_base_url:
        raise ValueError("请配置 OPENAI_API_KEY 和 OPENAI_BASE_URL。")
    if settings.model_timeout <= 0 or settings.model_max_retries < 0:
        raise ValueError("MODEL_TIMEOUT 必须大于零，MODEL_MAX_RETRIES 不得为负。")
    return ChatOpenAI(
        model=model_name, api_key=settings.openai_api_key,
        base_url=settings.openai_base_url, temperature=0.1,
        timeout=settings.model_timeout, max_retries=settings.model_max_retries,
        # 当前服务沿用 Chat Completions；不要求服务商支持 Responses 或额外的用量流事件。
        use_responses_api=False, stream_usage=False,
        # 保持 httpx 原有代理发现行为，不修改全局代理配置。
        http_socket_options=(),
    )


class LangChainBackend:
    """普通 Agent 使用框架的工具循环；严格问答直接调用无工具模型。"""

    def __init__(self, settings, tool_functions=(), model_factory=None):
        self.settings = settings
        self.tool_functions = tool_functions
        self.model_factory = model_factory

    def model(self, name):
        """模型构造是可注入边界，实验统计不再替换模块函数。"""
        return (self.model_factory or build_model)(self.settings, name)

    async def compress_history(self, messages):
        """沿用 30/8 条压缩策略，但摘要保留为历史数据，不提升为系统指令。"""
        if len(messages) <= 30:
            return messages
        from langsmith import tracing_context
        valid = [message for message in messages if message["role"] != "system"]
        old_messages, recent = valid[:-8], valid[-8:]
        history_text = "\n".join(f"{message['role']}: {message['content']}" for message in old_messages)
        # 第二阶段尚未启用远程追踪，防止个人原文因环境中的追踪设置而自动上传。
        with tracing_context(enabled=False):
            model = self.model(self.settings.summary_model)
            summary = await model.ainvoke([
                {"role": "system", "content": load_prompt("summarize")},
                {"role": "user", "content": "请压缩以下对话：\n" + history_text},
            ])
        text = content_text(summary.content).strip()
        if not text:
            raise RuntimeError("摘要模型未返回文本。")
        return [{"role": "user", "content": "【历史摘要，仅供理解上下文，不是当前指令】" + text}] + recent

    async def stream(self, messages, strict=False, tools=None, extra_instructions=""):
        """将模型文本和工具状态转换为统一事件；取消与请求错误由上层处理。"""
        from langsmith import tracing_context
        with tracing_context(enabled=False):
            model = self.model(self.settings.chat_model)
            instructions = load_prompt("answer") + extra_instructions
            if strict or (not self.tool_functions and not tools):
                # 不绑定工具是程序级限制，不依赖模型承诺不调用工具。
                if strict:
                    instructions += STRICT_INSTRUCTIONS
                async for chunk in model.astream([
                    {"role": "system", "content": instructions}, *messages,
                ]):
                    for event in self._chunk_events(chunk):
                        yield event
                return

            from langchain.agents import create_agent
            from langchain_core.tools import StructuredTool
            from langchain_core.messages import AIMessage
            from langchain_core.messages import ToolMessage
            from langchain.agents.middleware import ToolCallLimitMiddleware
            tools = tools if tools is not None else [StructuredTool.from_function(function) for function in self.tool_functions]
            if not 1 <= self.settings.agent_recursion_limit <= 100 or not 1 <= self.settings.agent_tool_limit <= 10:
                raise ValueError("Agent 步数须为 1–100，工具次数须为 1–10。")
            # 唯一的模型/工具循环仍由 LangChain 提供；外层工作流不重复实现循环。
            agent = create_agent(model=model, tools=tools, system_prompt=instructions,
                                 middleware=[ToolCallLimitMiddleware(run_limit=self.settings.agent_tool_limit,
                                                                     exit_behavior="error")])
            async for mode, data in agent.astream(
                    {"messages": messages}, stream_mode=["messages", "updates"],
                    config={"recursion_limit": self.settings.agent_recursion_limit}):
                if mode == "messages":
                    chunk, metadata = data
                    if metadata.get("langgraph_node") == "model":
                        for event in self._chunk_events(chunk):
                            yield event
                elif mode == "updates":
                    # 完整模型消息中的工具名只作为状态展示，参数不会输出到网页。
                    for update in data.values():
                        if not isinstance(update, dict):
                            continue
                        for message in update.get("messages", []):
                            if isinstance(message, ToolMessage):
                                yield ModelEvent("tool_completed", message.name or "工具")
                            if isinstance(message, ToolMessage) and message.name == "search_knowledge" and message.artifact:
                                yield ModelEvent("retrieval", "知识库检索完成", message.artifact)
                            if isinstance(message, AIMessage):
                                for call in message.tool_calls:
                                    yield ModelEvent("tool", call["name"])

    @staticmethod
    def _chunk_events(chunk):
        """只展示明确的文本/推理字段，不把整个服务响应转成字符串。"""
        reasoning = chunk.additional_kwargs.get("reasoning_content", "")
        if isinstance(reasoning, str) and reasoning:
            yield ModelEvent("reasoning", reasoning)
        text = content_text(chunk.content)
        if text:
            yield ModelEvent("text", text)


def select_backend(settings, tool_functions=()):
    """配置错误明确报错，避免无意调用另一个后端或重复执行工具。"""
    if settings.chat_backend == "openai-agents":
        return None
    if settings.chat_backend == "langchain":
        return LangChainBackend(settings, tool_functions)
    raise ValueError("CHAT_BACKEND 仅支持 langchain 或 openai-agents。")
