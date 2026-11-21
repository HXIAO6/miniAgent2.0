"""记录现有程序边界；文本攻击识别与事实核验留待后续阶段实现。"""
import asyncio
import json
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.application.chat import stream_chat
from miniagent.contracts import ChatDependencies, ChatRequest
from miniagent.knowledge.citations import evidence_json
from miniagent.ui.renderers import source_footer


class SecurityBoundaryTests(unittest.TestCase):
    def setUp(self):
        fixture = json.loads((ROOT / "evaluations/datasets/security_cases.json").read_text(encoding="utf-8"))
        self.cases = {case["id"]: case for case in fixture["cases"]}

    def test_source_html_is_escaped_and_benign_security_text_preserved(self):
        for case_id in ["html_payload", "security_lesson"]:
            text = self.cases[case_id]["text"]
            hit = dict(source="<img src=x onerror=alert(1)>", location="正文", text=text)
            rendered = source_footer([hit])
            self.assertNotIn("<script>", rendered)
            self.assertNotIn("<img", rendered)
            self.assertEqual(json.loads(evidence_json([hit]))[0]["text"], text)

    def test_document_instruction_does_not_enable_tools_in_strict_mode(self):
        # 已识别的恶意片段在模型前被拒绝；无可信证据时不启动 Runner。
        hit = dict(id="attack", source="合成攻击.md", location="正文",
                   text=self.cases["document_instruction"]["text"])
        kb, agent, runner = Mock(), Mock(), Mock()
        agent.instructions = "合成测试指令"
        kb.retrieve.return_value = dict(candidates=[hit], selected=[hit])
        async def no_events():
            if False:
                yield None
        runner.run_streamed.return_value = SimpleNamespace(stream_events=no_events)
        dependencies = ChatDependencies(kb, agent, runner, AsyncMock(side_effect=lambda messages: messages),
                                        logging.getLogger("test.security"))
        async def consume():
            return [event async for event in stream_chat(ChatRequest("根据资料回答"), dependencies)]
        asyncio.run(consume())
        runner.run_streamed.assert_not_called()
        agent.clone.assert_not_called()


if __name__ == "__main__":
    unittest.main()
