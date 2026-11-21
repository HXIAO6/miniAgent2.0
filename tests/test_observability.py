"""第五阶段：假密钥、合成事件与模拟 LangSmith 客户端，不发送远程数据。"""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.config import settings
from miniagent.contracts import ChatEvent, ChatRequest
from miniagent.observability.tracing import observed_events, security_decision
from miniagent.observability.langsmith import export_summary
from miniagent.cli.evaluate import compare_reports


class ObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        parent = ROOT / ".cache"
        parent.mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="observability-", dir=parent))
        self.config = replace(settings, trace_dir=self.root, trace_enabled=True)

    async def collect(self):
        async def events():
            security_decision("retrieval", "blocked")
            yield ChatEvent(kind="progress", history=[], answer="假秘密-body", status="secret-reasoning",
                            activity={"type": "tool.started", "name": "search_knowledge"})
            yield ChatEvent(kind="complete", history=[], answer="九天[资料1]", selected=[{"text": "私密原文"}])
        result = [event async for event in observed_events(events(), ChatRequest("私人问题"), self.config)]
        return result, json.loads(next(self.root.glob("*.json")).read_text(encoding="utf-8"))

    async def test_local_trace_is_allowlisted_and_export_drops_extra_fields(self):
        result, record = await self.collect()
        serialized = json.dumps(record, ensure_ascii=False)
        for text in ("私人问题", "假秘密", "secret-reasoning", "私密原文", "九天"):
            self.assertNotIn(text, serialized)
        self.assertEqual(result[-1].answer, "九天[资料1]")
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["security_counts"], {"retrieval.blocked": 1})
        record["prompt"] = "private-prompt"
        record["tools"]["private-tool-name"] = 1
        factory = Mock()
        export_summary(record, replace(self.config, langsmith_export_enabled=True, langsmith_api_key="synthetic"), factory)
        payload = factory.return_value.create_run.call_args.kwargs
        self.assertNotIn("private", json.dumps(payload, default=str))
        self.assertEqual(payload["outputs"]["selected_count"], 1)
        self.assertFalse(factory.call_args.kwargs["auto_batch_tracing"])
        factory.return_value.close.assert_called_once()

    async def test_remote_disabled_does_not_construct_client(self):
        _, record = await self.collect()
        factory = Mock()
        with self.assertRaises(ValueError):
            export_summary(record, replace(self.config, langsmith_export_enabled=False), factory)
        factory.assert_not_called()

    async def test_terminal_is_saved_before_consumer_stops(self):
        """HTTP 遇到终态即停止迭代，本地摘要此时必须已经存在。"""
        async def events():
            yield ChatEvent(kind="complete", history=[], answer="合成答案")
        iterator = observed_events(events(), ChatRequest("合成"), self.config)
        event = await anext(iterator)
        self.assertEqual(event.kind, "complete")
        self.assertEqual(len(list(self.root.glob("*.json"))), 1)
        await iterator.aclose()

    async def test_local_write_failure_does_not_fail_chat(self):
        from unittest.mock import patch
        async def events():
            yield ChatEvent(kind="complete", history=[], answer="正常回答")
        with patch("miniagent.observability.tracing._write", side_effect=OSError("synthetic")):
            result = [event async for event in observed_events(events(), ChatRequest("合成"), self.config)]
        self.assertEqual(result[-1].answer, "正常回答")

    async def test_cancel_failure_and_disabled_local_trace(self):
        async def broken():
            raise RuntimeError("synthetic-secret-error")
            yield
        with self.assertRaises(RuntimeError):
            async for _ in observed_events(broken(), ChatRequest("合成"), self.config):
                pass
        record = json.loads(next(self.root.glob("*.json")).read_text())
        self.assertEqual(record["status"], "failed")
        async def cancelled():
            raise asyncio.CancelledError()
            yield
        with self.assertRaises(asyncio.CancelledError):
            async for _ in observed_events(cancelled(), ChatRequest("合成"), self.config):
                pass
        self.assertEqual(len(list(self.root.glob("*.json"))), 2)
        async def empty():
            yield ChatEvent(kind="ignored", history=[])
        async for _ in observed_events(empty(), ChatRequest(""), replace(self.config, trace_enabled=False)):
            pass
        self.assertEqual(len(list(self.root.glob("*.json"))), 2)

    def test_comparison_rejects_different_dataset_and_reports_delta(self):
        before = dict(dataset_sha256="same", metrics=dict(protected_context_exposure=2, false_positives=0, factual_poisoning_detected=0))
        after = dict(dataset_sha256="same", metrics=dict(protected_context_exposure=1, false_positives=1, factual_poisoning_detected=0))
        result = compare_reports(before, after)
        self.assertEqual(result["protected_context_exposure"]["delta"], -1)
        self.assertEqual(result["false_positives"]["delta"], 1)
        with self.assertRaises(ValueError):
            compare_reports(before, dict(after, dataset_sha256="different"))
