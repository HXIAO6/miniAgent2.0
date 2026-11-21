"""HTTP 请求转为内部运行命令，应用层不依赖 Pydantic。"""
from miniagent.contracts import ChatRequest, RunCommand


def run_command(payload):
    """所有模型、历史、权限与数据路径仍由服务器提供。"""
    options = payload.options
    request = ChatRequest(message=payload.message, use_knowledge=options.mode != "chat",
        only_knowledge=options.only_knowledge, knowledge_mode="auto" if options.mode == "auto" else "forced",
        top_k=options.top_k, candidate_k=options.candidate_k, retrieval_mode=options.retrieval_mode,
        use_rerank=options.use_rerank, rerank_threshold=options.rerank_threshold, rerank_k=options.rerank_k)
    return RunCommand(str(payload.run_id), request)
