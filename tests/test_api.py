"""新 HTTP 入口回归：固定合成答案、隔离 SQLite 与临时 Chroma，不调用模型。"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from miniagent.api.app import create_app
from miniagent.api.schemas import RunRequest
from miniagent.api.mapping import run_command
from miniagent.application.chat_service import ChatService
from miniagent.config import settings
from miniagent.contracts import ChatEvent
from miniagent.knowledge.rag import KnowledgeBase
from miniagent.memory.thread_store import ThreadStore, legacy_messages


class ApiTests(unittest.TestCase):
    def setUp(self):
        root = settings.project_dir / ".cache"
        root.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="http-tests-", dir=root))
        self.config = replace(settings, web_memory_db=self.root / "web.sqlite3",
                              memory_db=self.root / "old.sqlite3", project_dir=self.root)
        self.kb = KnowledgeBase(self.root / "chroma", self.root / "knowledge")
        self.requests = []
        self.hit = dict(id="fixture", source="合成维护.md", location="正文", text="冷却液每九天更换。")

    async def executor(self, request, dependencies):
        self.requests.append(request)
        yield ChatEvent(kind="progress", history=[], answer="九天", status="正在检索")
        yield ChatEvent(kind="progress", history=[], answer="九天[资料1]。",
                        activity={"type": "tool.started", "name": "search_knowledge"})
        yield ChatEvent(kind="complete", history=[], answer="九天[资料1]。", selected=[self.hit],
                        candidates=[self.hit], update_scores=True, persist=True)

    def client(self):
        return TestClient(create_app(self.config, self.kb, executor=self.executor, dependency_factory=lambda: None))

    def test_stream_history_sources_and_thread_isolation(self):
        with self.client() as client:
            first = client.post("/api/threads").json()["id"]
            second = client.post("/api/threads").json()["id"]
            run_id = str(uuid.uuid4())
            response = client.post(f"/api/threads/{first}/runs", json={"message": "合成周期问题", "run_id": run_id})
            self.assertEqual(response.status_code, 200)
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            self.assertEqual(events[0]["type"], "run.started")
            self.assertEqual(events[-1]["type"], "run.completed")
            self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
            messages = client.get(f"/api/threads/{first}/messages").json()["messages"]
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[-1]["metadata"]["sources"][0]["text"], self.hit["text"])
            self.assertNotIn("<details", messages[-1]["content"])
            self.assertEqual(client.get(f"/api/threads/{second}/messages").json()["messages"], [])
            self.assertEqual(client.post(f"/api/threads/{first}/runs", json={"message": "重复", "run_id": run_id}).status_code, 409)
            client.post(f"/api/threads/{first}/runs", json={"message": "追问", "run_id": str(uuid.uuid4())})
            self.assertEqual(len(self.requests[-1].history), 2)
            self.assertEqual(client.post(f"/api/threads/{first}/runs", json={"message": " ", "run_id": str(uuid.uuid4())}).status_code, 422)
            self.assertEqual(client.post("/api/threads", headers={"Origin": "https://untrusted.example"}).status_code, 403)

    def test_document_upload_delete_confirmation_and_traversal(self):
        with self.client() as client, patch.object(self.kb, "embed", return_value=[[1., 0.]]):
            response = client.post("/api/documents/upload", files={"files": ("维护.md", "冷却液每九天更换。".encode(), "text/markdown")})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn("已导入", response.json()["result"])
            self.assertEqual(client.get("/api/documents").json()["documents"][0]["source"], "维护.md")
            self.assertEqual(client.post("/api/documents/delete", json={"sources": ["维护.md"]}).status_code, 422)
            self.assertEqual(client.post("/api/documents/upload", files={"files": ("../escape.md", b"bad")}).status_code, 422)
            removed = client.post("/api/documents/delete", json={"sources": ["维护.md"], "confirmed": True})
            self.assertIn("已删除", removed.json()["result"])
            self.assertEqual(client.get("/api/documents").json()["documents"], [])

    def test_legacy_reader_is_readonly_and_does_not_render_html(self):
        with sqlite3.connect(self.config.memory_db) as database:
            database.execute("CREATE TABLE messages(id INTEGER,role TEXT,content TEXT,conversation_id INTEGER)")
            database.execute("INSERT INTO messages VALUES (1,'assistant',?,1)",
                             ("<details>过程</details>九天<!-- rag-sources --><script>攻击</script>",))
        before = self.config.memory_db.read_bytes()
        self.assertEqual(legacy_messages(self.config.memory_db)[0]["content"], "九天")
        self.assertEqual(before, self.config.memory_db.read_bytes())


class CancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_saves_partial_and_unlocks(self):
        root = settings.project_dir / ".cache"
        root.mkdir(exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix="cancel-api-", dir=root)) / "web.sqlite3"
        store = ThreadStore(path)
        thread = store.create_thread()["id"]
        produced = asyncio.Event()
        async def executor(request, dependencies):
            yield ChatEvent(kind="progress", history=[], answer="部分回答")
            produced.set()
            await asyncio.sleep(60)
        lock = asyncio.Lock()
        service = ChatService(settings, None, store, lock, executor=executor, dependency_factory=lambda: None)
        run_id, queue = await service.start(thread, run_command(RunRequest(message="合成问题", run_id=uuid.uuid4())))
        await produced.wait()
        await service.cancel(run_id)
        self.assertFalse(lock.locked())
        message = store.messages(thread)[-1]
        self.assertEqual(message["content"], "部分回答")
        self.assertEqual(message["metadata"]["status"], "cancelled")
        self.assertEqual(store.get_run(run_id)["status"], "cancelled")

    async def test_failed_run_masks_error_and_is_excluded_from_context(self):
        """合成敏感异常不返回浏览器；失败整轮不会污染下一次模型历史。"""
        root = settings.project_dir / ".cache"
        root.mkdir(exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix="failed-api-", dir=root)) / "web.sqlite3"
        store = ThreadStore(path)
        thread = store.create_thread()["id"]
        requests = []
        async def executor(request, dependencies):
            requests.append(request)
            if len(requests) == 1:
                raise RuntimeError("secret-token-for-test-only")
            yield ChatEvent(kind="complete", history=[], answer="合成回答")
        lock = asyncio.Lock()
        service = ChatService(settings, None, store, lock, executor=executor, dependency_factory=lambda: None)
        for index in range(2):
            run_id, queue = await service.start(thread, run_command(RunRequest(message=f"合成问题{index}", run_id=uuid.uuid4())))
            events = [event async for event in service.events(run_id, queue) if event]
            self.assertNotIn("secret-token", json.dumps(events))
            self.assertFalse(lock.locked())
        self.assertEqual(requests[1].history, [])
        self.assertEqual(len(store.messages(thread)), 4)

    async def test_immediate_cancel_busy_and_restart_recovery(self):
        """验证刚创建就取消、运行冲突以及进程重启的明确终态。"""
        root = settings.project_dir / ".cache"
        root.mkdir(exist_ok=True)
        path = Path(tempfile.mkdtemp(prefix="restart-api-", dir=root)) / "web.sqlite3"
        store = ThreadStore(path)
        thread = store.create_thread()["id"]
        async def executor(request, dependencies):
            await asyncio.sleep(60)
            yield ChatEvent(kind="complete", history=[], answer="不会完成")
        lock = asyncio.Lock()
        service = ChatService(settings, None, store, lock, executor=executor, dependency_factory=lambda: None)
        run_id, queue = await service.start(thread, run_command(RunRequest(message="取消测试", run_id=uuid.uuid4())))
        from miniagent.application.chat_service import BusyError
        with self.assertRaises(BusyError):
            await service.start(thread, run_command(RunRequest(message="并行测试", run_id=uuid.uuid4())))
        await service.cancel(run_id)
        self.assertFalse(lock.locked())
        self.assertEqual(store.get_run(run_id)["status"], "cancelled")
        interrupted = str(uuid.uuid4())
        store.start_run(thread, interrupted, "模拟上次未完成运行")
        ThreadStore(path).recover()
        self.assertEqual(store.get_run(interrupted)["status"], "interrupted")
        self.assertEqual(store.messages(thread)[-1]["metadata"]["status"], "interrupted")


if __name__ == "__main__":
    unittest.main()
