"""Gradio 事件适配；控件数据转换留在这里，业务用例位于 application。"""
import asyncio
import sqlite3
import gradio as gr

from miniagent.config import settings, logger
from miniagent.bootstrap import build_chat_dependencies
from miniagent.application.chat import stream_chat, message_content_to_text
from miniagent.application.documents import DocumentService
from miniagent.contracts import ChatRequest
from miniagent.knowledge.rag import knowledge_base, DEFAULT_RERANK_THRESHOLD
from miniagent.memory.context import MemoryContext
from miniagent.ui.renderers import render_assistant_message, source_footer, candidate_table
from miniagent.adapters.legacy import Runner, compress_history

_memory_context = MemoryContext()
_demo = None


def load_history():
    """从 SQLite 读取短期记忆。"""
    return _get_memory_store().load_messages()


def _get_memory_store():
    """由当前配置获取存储，导入回调模块本身不打开数据库。"""
    return _memory_context.get_store(settings.memory_db)


def _persist_turn(ui_history):
    """只追加当前轮，不再覆盖整个历史文件；界面 HTML 仍按旧格式保存。"""
    if len(ui_history) < 2:
        return
    user = ui_history[-2].get("content", "") if ui_history[-2].get("role") == "user" else ""
    assistant = ui_history[-1].get("content", "") if ui_history[-1].get("role") == "assistant" else ""
    _get_memory_store().append_turn(message_content_to_text(user), message_content_to_text(assistant))

async def predict(message, history, use_knowledge=True, top_k=4, candidate_k=20,
                  retrieval_mode="hybrid", show_scores=False, use_rerank=True,
                  rerank_threshold=DEFAULT_RERANK_THRESHOLD, rerank_k=20, only_knowledge=settings.strict_knowledge_default,
                  knowledge_mode="forced"):
    """将服务事件转换为原有 Gradio 回调格式，保持网页 API 和 SQLite 格式兼容。"""
    request = ChatRequest(
        message=message, history=history or [], use_knowledge=use_knowledge,
        top_k=top_k, candidate_k=candidate_k, retrieval_mode=retrieval_mode,
        use_rerank=use_rerank, rerank_threshold=rerank_threshold,
        rerank_k=rerank_k, only_knowledge=only_knowledge, knowledge_mode=knowledge_mode)
    # 应用装配层选择模型后端，回调只负责事件到控件数据的转换。
    dependencies = build_chat_dependencies(settings, knowledge_base, logger, Runner, compress_history)
    async for event in stream_chat(request, dependencies):
        if event.kind == "ignored":
            yield "", event.history
            continue
        answer = event.answer
        if event.kind == "complete":
            answer += source_footer(event.selected)
        ui_history = event.history + [{
            "role": "assistant",
            "content": render_assistant_message(
                answer, event.status, event.elapsed_seconds, event.expanded),
        }]
        # 存储沿用旧版展示格式，现有数据库不需要迁移。
        if event.persist:
            try:
                _persist_turn(ui_history)
            except (OSError, RuntimeError, sqlite3.Error) as error:
                logger.error("聊天记录保存失败，类型=%s", type(error).__name__)
        if show_scores and event.update_scores:
            yield "", ui_history, candidate_table(event.candidates, len(event.selected), event.selected)
        else:
            yield "", ui_history


def clear_history():
    """清空 SQLite 当前会话，不删除知识库。"""
    _get_memory_store().clear()
    return [], ""

async def upload_documents(files, chunk_chars=1200, overlap_chars=180):
    return await DocumentService(knowledge_base).upload(files, chunk_chars, overlap_chars)


async def predict_with_scores(message, history, use_knowledge, top_k, candidate_k, retrieval_mode,
                              use_rerank=True, rerank_threshold=DEFAULT_RERANK_THRESHOLD,
                              rerank_k=20, only_knowledge=settings.strict_knowledge_default, knowledge_mode="forced"):
    """前端同时更新聊天与候选表；流式文字到达时保留已经展示的分数。"""
    first = True
    async for result in predict(message, history, use_knowledge, top_k, candidate_k, retrieval_mode,
                                show_scores=True, use_rerank=use_rerank, rerank_threshold=rerank_threshold,
                                rerank_k=rerank_k, only_knowledge=only_knowledge, knowledge_mode=knowledge_mode):
        if len(result) == 3:
            yield result
        else:
            yield result[0], result[1], [] if first else gr.skip()
        first = False


async def refresh_knowledge():
    try:
        return await asyncio.to_thread(knowledge_base.status)
    except Exception as error:
        return f"知识库状态读取失败：{error}"


async def refresh_document_panel():
    """同时刷新文件清单、选择器和计数，清空过期候选及删除确认。"""
    documents, status = await DocumentService(knowledge_base).snapshot()
    rows = [[doc["source"], doc["chunk_count"], "存在" if doc["has_file"] else "缺失（可清理残留索引）"]
            for doc in documents]
    return (rows, gr.Dropdown(choices=[doc["source"] for doc in documents], value=[], multiselect=True),
            status, False, "", [])


def preview_deletion(sources):
    """每次选择变化都撤销之前的确认，避免换了文件却沿用旧确认。"""
    if not sources:
        return "", False
    return ("待删除文档：\n" + "\n".join(f"• {source}" for source in sources)
            + f"\n共 {len(sources)} 个。删除后不再用于回答，原文件移入回收站。历史聊天和旧版本保留。", False)


async def delete_documents(sources, confirmed):
    """仅供文档管理界面调用，不注册为 Agent 工具。逐文件报告结果，允许部分失败。"""
    if not isinstance(sources, list) or not sources:
        return "请先选择要删除的文档。", *(gr.skip() for _ in range(6))
    if confirmed is not True:
        return "请核对待删除文件列表，并勾选确认后再删除。", *(gr.skip() for _ in range(6))
    result = await DocumentService(knowledge_base).delete(sources, confirmed=confirmed)
    try:
        return result, *await refresh_document_panel()
    except Exception as error:
        # 删除结果不能被一次刷新失败掩盖。清空候选与确认，并要求手动刷新清单。
        return result + f"\n清单刷新失败：{error}，请手动刷新。", gr.skip(), gr.skip(), gr.skip(), False, "", []



def __getattr__(name):
    """旧脚本访问 app.demo 时才构建页面，单纯导入不读取聊天历史。"""
    global _demo
    if name == "demo":
        if _demo is None:
            import sys
            from miniagent.ui.app import create_app
            _demo = create_app(sys.modules[__name__])
        return _demo
    raise AttributeError(name)
