"""用本地 HTTP 模拟验证真实 LangChain 请求协议，不访问模型服务或个人资料。"""
import asyncio
from dataclasses import replace
import json
import logging
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
from langchain_openai import ChatOpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.adapters import llm
from miniagent.config import settings
from miniagent.application.chat import stream_chat
from miniagent.contracts import ChatDependencies, ChatRequest


def sse(delta, finish=None):
    """构造 OpenAI 兼容流事件，走实际 ChatOpenAI 解码路径。"""
    payload = dict(id="synthetic", object="chat.completion.chunk", model="fixture-model",
                   choices=[dict(index=0, delta=delta, finish_reason=finish)])
    return "data: " + json.dumps(payload) + "\n\n"


def fixture_clock() -> str:
    """查询固定测试时间，不读取系统或文件。"""
    return "2099-01-01 12:34:56"


class LangChainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = replace(settings, openai_base_url="https://fixture.invalid/v1",
                                openai_api_key="synthetic-key", chat_model="fixture-model",
                                summary_model="fixture-summary", model_max_retries=0,
                                chat_backend="langchain")
        self.requests = []

    def handler(self, request):
        payload = json.loads(request.content)
        self.requests.append(payload)
        if payload.get("tools") and not any(message["role"] == "tool" for message in payload["messages"]):
            call = dict(index=0, id="fixture-call", type="function",
                        function=dict(name="fixture_clock", arguments="{}"))
            content = sse(dict(role="assistant", tool_calls=[call])) + sse({}, "tool_calls")
        else:
            content = sse(dict(role="assistant", content="九天")) + sse(dict(content="[资料1]。")) + sse({}, "stop")
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text=content + "data: [DONE]\n\n")

    def model(self, name, client):
        return ChatOpenAI(model=name, api_key="synthetic-key", base_url=self.settings.openai_base_url,
                          http_async_client=client, max_retries=0, stream_usage=False, use_responses_api=False)

    async def test_real_http_stream_and_strict_mode_never_sends_tools(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handler)) as client:
            with patch.object(llm, "build_model", side_effect=lambda config, name: self.model(name, client)):
                backend = llm.LangChainBackend(self.settings, [fixture_clock])
                events = [event async for event in backend.stream([{"role": "user", "content": "合成手册"}], strict=True)]
        self.assertEqual("".join(event.text for event in events), "九天[资料1]。")
        self.assertNotIn("tools", self.requests[0])
        self.assertIn("仅依据知识库", self.requests[0]["messages"][0]["content"])

    async def test_framework_tool_loop_returns_tool_result_to_model(self):
        async with httpx.AsyncClient(transport=httpx.MockTransport(self.handler)) as client:
            with patch.object(llm, "build_model", side_effect=lambda config, name: self.model(name, client)):
                backend = llm.LangChainBackend(self.settings, [fixture_clock])
                events = [event async for event in backend.stream([{"role": "user", "content": "测试时间"}])]
        self.assertTrue(any(event.kind == "tool" and event.text == "fixture_clock" for event in events))
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(any(message.get("content") == fixture_clock() and message["role"] == "tool"
                            for message in self.requests[-1]["messages"]))

    async def test_summary_uses_summary_model_and_keeps_recent_eight(self):
        model = Mock()
        model.ainvoke = AsyncMock(return_value=Mock(content="合成历史摘要"))
        messages = [{"role": "user" if index % 2 == 0 else "assistant", "content": f"消息{index}"}
                    for index in range(32)]
        with patch.object(llm, "build_model", return_value=model) as factory:
            backend = llm.LangChainBackend(self.settings)
            self.assertEqual(await backend.compress_history(messages[:30]), messages[:30])
            factory.assert_not_called()
            result = await backend.compress_history(messages)
        self.assertEqual(result[1:], messages[-8:])
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(factory.call_args.args[1], "fixture-summary")
        self.assertNotIn("消息31", model.ainvoke.call_args.args[0][-1]["content"])

    async def test_http_errors_timeout_and_cancellation_propagate(self):
        for error in [httpx.ReadTimeout("synthetic timeout"), asyncio.CancelledError()]:
            model = Mock()
            async def broken(messages):
                raise error
                yield
            model.astream = broken
            with patch.object(llm, "build_model", return_value=model):
                with self.assertRaises(type(error)):
                    async for _ in llm.LangChainBackend(self.settings).stream([]):
                        pass
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401, json={
            "error": {"message": "synthetic denied", "type": "authentication_error"}}))) as client:
            with patch.object(llm, "build_model", side_effect=lambda config, name: self.model(name, client)):
                from openai import AuthenticationError
                with self.assertRaises(AuthenticationError):
                    async for _ in llm.LangChainBackend(self.settings).stream([]):
                        pass

    async def test_zero_evidence_never_calls_new_backend(self):
        kb, backend = Mock(), Mock()
        kb.retrieve.return_value = dict(candidates=[], selected=[])
        dependencies = ChatDependencies(kb, None, None, None, logging.getLogger("test"), backend)
        events = [event async for event in stream_chat(ChatRequest("缺少资料"), dependencies)]
        self.assertEqual(events[-1].kind, "refusal")
        backend.compress_history.assert_not_called()
        backend.stream.assert_not_called()

    async def test_explicit_configuration_and_backend_switch(self):
        model = llm.build_model(self.settings, self.settings.chat_model)
        self.assertEqual(model.model_name, "fixture-model")
        self.assertEqual(model.openai_api_base, self.settings.openai_base_url)
        self.assertIsNone(llm.select_backend(replace(self.settings, chat_backend="openai-agents")))
        with self.assertRaises(ValueError):
            llm.select_backend(replace(self.settings, chat_backend="typo"))
        with self.assertRaises(ValueError):
            llm.build_model(replace(self.settings, openai_base_url=""), "fixture-model")


if __name__ == "__main__":
    unittest.main()
