"""第三阶段离线工作流测试：真实框架 + 模拟 HTTP，只用虚构手册和固定响应。"""
import asyncio
from dataclasses import replace
import json
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import httpx
from langchain_openai import ChatOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.adapters import llm
from miniagent.application.chat import stream_chat
from miniagent.config import settings
from miniagent.contracts import ChatDependencies, ChatRequest
from miniagent.tools.retrieval import RetrievalSession


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = replace(settings, chat_backend="langchain", openai_api_key="synthetic",
                                openai_base_url="https://fixture.invalid/v1", agent_tool_limit=2)
        self.hit = dict(id="manual", source="合成维护.md", location="正文", text="冷却液每九天更换。")
        self.kb = Mock()
        self.kb.retrieve.return_value = dict(candidates=[self.hit], selected=[self.hit])
        self.requests = []
        self.repeat = False
        self.greeting = False

    def handler(self, request):
        payload = json.loads(request.content)
        self.requests.append(payload)
        tool_messages = [message for message in payload["messages"] if message["role"] == "tool"]
        if not self.greeting and (not tool_messages or self.repeat):
            call = dict(index=0, id=f"call-{len(self.requests)}", type="function",
                        function=dict(name="search_knowledge", arguments=json.dumps({"query": "冷却液周期"})))
            delta, finish = dict(role="assistant", tool_calls=[call]), "tool_calls"
        else:
            delta, finish = dict(role="assistant", content="你好" if self.greeting else "九天[资料1]。"), "stop"
        chunks = []
        for value, reason in [(delta, None), ({}, finish)]:
            chunks.append("data: " + json.dumps(dict(id="fixture", object="chat.completion.chunk",
                choices=[dict(index=0, delta=value, finish_reason=reason)])) + "\n\n")
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text="".join(chunks) + "data: [DONE]\n\n")

    async def run_auto(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handler)) as client:
            model = ChatOpenAI(model="fixture", api_key="synthetic", base_url=self.settings.openai_base_url,
                               http_async_client=client, max_retries=0, stream_usage=False,
                               use_responses_api=False, http_socket_options=())
            with patch.object(llm, "build_model", return_value=model):
                backend = llm.LangChainBackend(self.settings)
                dependencies = ChatDependencies(self.kb, None, None, None, logging.getLogger("test"), backend)
                return [event async for event in stream_chat(
                    ChatRequest("你好" if self.greeting else "根据我的手册查冷却周期", knowledge_mode="auto"), dependencies)]

    async def test_auto_retrieval_and_citations_follow_real_tool_artifact(self):
        events = await self.run_auto()
        self.assertEqual(events[-1].kind, "complete")
        self.assertEqual(events[-1].selected, [self.hit])
        self.assertIn("[资料1]", events[-1].answer)
        self.kb.retrieve.assert_called_once()
        tool_names = [tool["function"]["name"] for tool in self.requests[0]["tools"]]
        self.assertEqual(tool_names, ["search_knowledge"])
        self.assertTrue(any("冷却液每九天更换" in message.get("content", "")
                            for message in self.requests[-1]["messages"] if message["role"] == "tool"))

    async def test_greeting_skips_retrieval(self):
        self.greeting = True
        events = await self.run_auto()
        self.kb.retrieve.assert_not_called()
        self.assertEqual(events[-1].answer, "你好")
        self.assertEqual(events[-1].selected, [])

    async def test_empty_result_does_not_create_fake_citation(self):
        self.kb.retrieve.return_value = dict(candidates=[], selected=[])
        final = (await self.run_auto())[-1]
        self.assertEqual(final.selected, [])
        self.assertIn("[引用无效，需核对]", final.answer)
        self.assertNotIn("[资料1]", final.answer)

    async def test_repeated_calls_stop_at_budget(self):
        self.repeat = True
        final = (await self.run_auto())[-1]
        self.assertEqual(final.kind, "error")
        self.assertLessEqual(self.kb.retrieve.call_count, 2)
        self.assertLessEqual(len(self.requests), 3)

    async def test_retrieval_numbers_deduplicate_and_reset_between_runs(self):
        request = ChatRequest("查询", top_k=2)
        session = RetrievalSession(self.kb, request, max_calls=3)
        await session.search("第一次")
        second = dict(id="second", source="备份.md", location="正文", text="保留十四天。")
        self.kb.retrieve.return_value = dict(candidates=[second, self.hit], selected=[second, self.hit])
        content, artifact = await session.search("第二次")
        self.assertEqual([hit["id"] for hit in artifact["selected"]], ["manual", "second"])
        self.assertIn('"citation": "资料2"', content)
        artifact["selected"].clear()
        self.assertEqual(len(session.selected), 2)
        self.assertTrue(all(hit["decision"] == "本轮累计选入回答" for hit in artifact["candidates"]))
        other = RetrievalSession(self.kb, request)
        self.assertEqual(other.selected, [])

    async def test_validation_and_total_context_budget(self):
        session = RetrievalSession(self.kb, ChatRequest("查询"), max_calls=1)
        for query in ["", " " * 3, "x" * 2001]:
            with self.assertRaises(ValueError):
                await session.search(query)
        await session.search("有效查询")
        with self.assertRaises(RuntimeError):
            await session.search("超限查询")
        self.kb.retrieve.assert_called_once()
        # 即使库返回异常巨大的片段，工具累计上下文仍不能绕过原字符预算。
        large = dict(self.hit, text="字" * 12001)
        self.kb.retrieve.return_value = dict(candidates=[large], selected=[large])
        _, artifact = await RetrievalSession(self.kb, ChatRequest("查询")).search("超长资料")
        self.assertEqual(artifact["selected"], [])

    async def test_legacy_auto_mode_is_rejected_without_calling_model(self):
        dependencies = ChatDependencies(self.kb, Mock(), Mock(), Mock(), logging.getLogger("test"))
        events = [event async for event in stream_chat(ChatRequest("查询", knowledge_mode="auto"), dependencies)]
        self.assertEqual(events[-1].kind, "error")
        # API 层有明确的参数提示；应用层异常统一隐藏，避免泄露 SDK 细节。
        self.assertIn("运行失败", events[-1].answer)
        self.kb.retrieve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
