"""统一会话与运行服务；HTTP 只消费结构化事件，不管理模型上下文或存储格式。"""
import asyncio
from miniagent.application.chat import stream_chat
from miniagent.config import logger
from miniagent.contracts import RunCommand
from dataclasses import replace


class BusyError(Exception):
    """单机单进程同一时刻仅执行一轮聊天或资料变更。"""


class ChatService:
    """服务端历史为唯一事实来源；每轮运行有独立 ID、顺序号及明确终态。"""

    def __init__(self, settings, knowledge_base, store, operation_lock, executor=stream_chat, dependency_factory=None):
        self.settings = settings
        self.knowledge_base = knowledge_base
        self.store = store
        self.lock = operation_lock
        self.executor = executor
        if dependency_factory is None:
            raise ValueError("请通过 bootstrap 装配聊天依赖，或显式注入 dependency_factory。")
        self.dependency_factory = dependency_factory
        self.active = {}

    async def start(self, thread_id, payload: RunCommand):
        if self.lock.locked():
            raise BusyError("另一个操作正在执行，请稍后重试。")
        rows = self.store.messages(thread_id)
        history = []
        # 存储按用户/助手成对写入；失败或取消的整轮不进入后续模型上下文。
        for user, assistant in zip(rows[::2], rows[1::2]):
            if assistant["metadata"].get("status") in {"completed", "refusal"}:
                history.extend(dict(role=row["role"], content=row["content"]) for row in (user, assistant) if row["content"])
        await self.lock.acquire()
        run_id = str(payload.run_id)
        try:
            message_id = self.store.start_run(thread_id, run_id, payload.request.message)
        except BaseException:
            self.lock.release()
            raise
        queue = asyncio.Queue(maxsize=256)
        request = replace(payload.request, history=history)
        task = asyncio.create_task(self._produce(thread_id, run_id, message_id, request, queue))
        self.active[run_id] = task
        # 让生产任务先进入 try/finally，立即点击停止也能释放操作锁并写入终态。
        await asyncio.sleep(0)
        return run_id, queue

    async def _produce(self, thread_id, run_id, message_id, request, queue):
        sequence = 0
        answer, status_text = "", ""
        metadata = {"sources": [], "candidates": [], "tools": [], "elapsed_seconds": 0}
        terminal = "failed"

        async def emit(kind, data):
            nonlocal sequence
            sequence += 1
            await queue.put(dict(type=kind, seq=sequence, run_id=run_id, thread_id=thread_id,
                                 message_id=message_id, data=data))

        try:
            await emit("run.started", {})
            dependencies = self.dependency_factory()
            async for event in self.executor(request, dependencies):
                safe_answer = "运行失败，请检查模型服务状态后重试。" if event.kind == "error" else event.answer
                if safe_answer != answer:
                    # 后处理可能将无效引用改写；用 replace 事件明确替换，不能只拼接 delta。
                    if safe_answer.startswith(answer):
                        await emit("message.delta", {"text": safe_answer[len(answer):]})
                    else:
                        await emit("message.replace", {"text": safe_answer})
                    answer = safe_answer
                if event.status != status_text:
                    status_text = event.status
                    await emit("run.status", {"text": status_text})
                metadata["elapsed_seconds"] = event.elapsed_seconds
                if event.activity:
                    activity = dict(event.activity)
                    metadata["tools"].append(activity)
                    await emit(activity["type"], {"name": activity["name"]})
                if event.update_scores:
                    metadata["sources"] = self.public_hits(event.selected)
                    metadata["candidates"] = self.public_hits(event.candidates)
                    await emit("retrieval.completed", {"sources": metadata["sources"], "candidates": metadata["candidates"]})
                if event.kind in {"complete", "refusal", "error"}:
                    terminal = {"complete": "completed", "refusal": "refusal", "error": "failed"}[event.kind]
                    break
            else:
                raise RuntimeError("工作流未返回结束状态。")
            metadata["status_text"] = status_text
            self.store.finish_run(run_id, answer, metadata, terminal)
            await emit("run.failed" if terminal == "failed" else "run.completed",
                       {"status": terminal, "message": self.store.messages(thread_id)[-1]})
        except asyncio.CancelledError:
            terminal = "cancelled"
            metadata["status_text"] = "已停止生成"
            self.store.finish_run(run_id, answer, metadata, terminal)
            # 取消可能由浏览器断连触发，不能因无人消费的队列满而阻塞清理。
            if not queue.full():
                sequence += 1
                queue.put_nowait(dict(type="run.cancelled", seq=sequence, run_id=run_id,
                    thread_id=thread_id, message_id=message_id,
                    data={"status": terminal, "message": self.store.messages(thread_id)[-1]}))
        except Exception as error:
            logger.error("HTTP 聊天运行失败，类型=%s", type(error).__name__)
            # 日志和客户端不回传 SDK 异常详情，避免连接地址、凭据或内部路径泄露。
            metadata["error"] = "运行失败，请检查服务状态后重试。"
            self.store.finish_run(run_id, answer, metadata, "failed")
            if not queue.full():
                sequence += 1
                queue.put_nowait(dict(type="run.failed", seq=sequence, run_id=run_id,
                    thread_id=thread_id, message_id=message_id, data={"error": metadata["error"]}))
        finally:
            self.active.pop(run_id, None)
            self.lock.release()
            # 消费端同时检查 task.done()，不用向满队列追加结束哨兵。

    @staticmethod
    def public_hits(hits):
        """仅发布原文及诊断字段，绝不通过 HTTP 暴露向量、内部路径或全量存储对象。"""
        keys = ("id", "source", "location", "text", "similarity", "bm25_score", "rrf_score",
                "rerank_score", "decision", "rerank_windows", "query_truncated")
        return [{key: hit[key] for key in keys if key in hit} for hit in hits]

    async def cancel(self, run_id):
        self.store.get_run(run_id)
        task = self.active.get(run_id)
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return self.store.get_run(run_id)

    async def events(self, run_id, queue):
        task = self.active.get(run_id)
        try:
            while not queue.empty() or (task and not task.done()):
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=1)
                except asyncio.TimeoutError:
                    if not task.done():
                        yield None
        finally:
            # HTTP 断开会关闭生成器；取消模型任务并等待消息以 cancelled 状态保存。
            if task and not task.done():
                await asyncio.shield(self.cancel(run_id))

    async def close(self):
        for run_id in list(self.active):
            await self.cancel(run_id)
