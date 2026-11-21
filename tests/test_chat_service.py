"""离线验证聊天服务契约，不创建 Gradio、不访问模型或正式知识库。"""
import asyncio
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from chat_service import stream_chat
from contracts import ChatDependencies, ChatRequest


def sdk_text(text):
    """构造旧 SDK 的文本增量，固定模型输出便于比较重构行为。"""
    return SimpleNamespace(type="raw_response_event", data=SimpleNamespace(
        type="response.output_text.delta", delta=text))


class FakeRun:
    def __init__(self, events):
        self.events = events

    async def stream_events(self):
        for event in self.events:
            yield event


class ChatServiceTests(unittest.TestCase):
    def setUp(self):
        self.hit = dict(id="manual", source="维护.md", location="第 1 行",
                        text="冷却液每九天更换。", rerank_score=.9)
        self.kb = Mock()
        self.kb.retrieve.return_value = dict(candidates=[self.hit], selected=[self.hit])
        self.agent = Mock()
        self.agent.instructions = "合成测试指令"
        self.runner = Mock()
        self.runner.run_streamed.return_value = FakeRun([
            sdk_text("九天[资料1]。"), sdk_text("错误编号[资料9]。")])
        self.compress = AsyncMock(side_effect=lambda messages: messages)
        self.dependencies = ChatDependencies(
            self.kb, self.agent, self.runner, self.compress, logging.getLogger("test.chat"))

    def collect(self, request):
        async def consume():
            return [event async for event in stream_chat(request, self.dependencies)]
        return asyncio.run(consume())

    def test_strict_answer_preserves_evidence_and_disables_tools(self):
        events = self.collect(ChatRequest("多久更换？"))
        final = events[-1]
        self.assertEqual(final.kind, "complete")
        self.assertTrue(final.persist)
        self.assertIn("九天[资料1]", final.answer)
        self.assertIn("[引用无效，需核对]", final.answer)
        self.assertNotIn("<details", final.answer)
        self.assertEqual(final.selected, [self.hit])
        self.assertEqual(self.agent.clone.call_args.kwargs["tools"], [])
        self.assertIs(self.runner.run_streamed.call_args.args[0], self.agent.clone.return_value)
        self.assertIn("冷却液每九天更换", self.runner.run_streamed.call_args.args[1][-1]["content"])

    def test_zero_evidence_skips_model_and_summary(self):
        self.kb.retrieve.return_value = dict(candidates=[], selected=[])
        final = self.collect(ChatRequest("不存在的资料"))[-1]
        self.assertEqual(final.kind, "refusal")
        self.assertIn("没有找到足够相关", final.answer)
        self.runner.run_streamed.assert_not_called()
        self.compress.assert_not_awaited()

    def test_normal_chat_and_tool_events_use_existing_agent(self):
        self.runner.run_streamed.return_value = FakeRun([
            SimpleNamespace(type="run_item_stream_event", name="tool_called",
                            item=SimpleNamespace(raw_item=SimpleNamespace(name="get_current_time"))),
            sdk_text("你好"),
        ])
        events = self.collect(ChatRequest("你好", use_knowledge=False))
        self.kb.retrieve.assert_not_called()
        self.agent.clone.assert_not_called()
        self.assertIs(self.runner.run_streamed.call_args.args[0], self.agent)
        self.assertTrue(any("get_current_time" in event.status for event in events))
        self.assertEqual(events[-1].answer, "你好")

    def test_history_strips_display_markup_without_mutating_input(self):
        history = [{"role": "assistant", "content":
                    "<details>旧过程</details>旧回答<!-- rag-sources -->旧原文"}]
        self.collect(ChatRequest("继续", history=history, use_knowledge=False))
        sent = self.runner.run_streamed.call_args.args[1]
        self.assertEqual(sent[0]["content"], "旧回答")
        self.assertIn("旧原文", history[0]["content"])

    def test_error_is_an_event_and_cancellation_is_not_swallowed(self):
        self.kb.retrieve.side_effect = RuntimeError("离线模拟错误")
        final = self.collect(ChatRequest("查询"))[-1]
        self.assertEqual(final.kind, "error")
        self.assertIn("离线模拟错误", final.answer)
        self.kb.retrieve.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            self.collect(ChatRequest("取消"))

    def test_empty_input_and_event_snapshots(self):
        self.assertEqual(self.collect(ChatRequest("  "))[-1].kind, "ignored")
        self.runner.run_streamed.assert_not_called()
        events = self.collect(ChatRequest("查询"))
        self.hit["text"] = "事后更改"
        self.assertEqual(events[-1].selected[0]["text"], "冷却液每九天更换。")


if __name__ == "__main__":
    unittest.main()
