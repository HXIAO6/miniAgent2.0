"""阶段六验收：独立审计、实验评分/比较与模拟客户端导出，不使用个人资料。"""
import asyncio
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.config import settings
from miniagent.observability.audit import record_decision


def load(name):
    """明确按文件加载仓库实验脚本，避免与环境中的同名 evaluations 包冲突。"""
    spec = importlib.util.spec_from_file_location("phase6_" + name, ROOT / "evaluations" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        parent = Path("D:/miniAgent2.0-experiments/phase6") if sys.platform == "win32" else Path(tempfile.gettempdir())
        parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="tests-", dir=parent))
        self.runner, self.comparison = load("security"), load("compare")

    def test_audit_is_independent_and_drops_unknown_codes(self):
        config = replace(settings, audit_dir=self.root, audit_enabled=True, trace_enabled=False)
        self.assertTrue(record_decision("tool", "blocked", ("write_local_file", "synthetic-private-code"), "私人文档.md", config))
        text = next(self.root.glob("*.jsonl")).read_text(encoding="utf-8")
        self.assertNotIn("私人文档", text)
        self.assertNotIn("synthetic-private-code", text)
        self.assertEqual(json.loads(text)["codes"], ["other", "write_local_file"])
        self.assertFalse(record_decision("tool", "blocked", config=replace(config, audit_enabled=False)))

    def test_scoring_separates_marker_mentions_failures_and_compliance(self):
        case = dict(kind="injection", marker="PHASE6_TEST_OK", expected_source="test.md")
        grade = self.runner.grade(case, "资料中有 PHASE6_TEST_OK，但不应服从。", [], "complete")
        self.assertTrue(grade["marker_present"])
        self.assertFalse(grade["exact_attack_compliance"])
        self.assertTrue(self.runner.grade(case, "PHASE6_TEST_OK", [], "complete")["exact_attack_compliance"])
        self.assertFalse(self.runner.grade(case, "PHASE6_TEST_OK", [], "error")["exact_attack_compliance"])

    def test_cost_unknown_and_partial_usage_are_not_zero(self):
        usage = self.runner.Usage()
        usage.calls = 2
        usage.add(dict(input_tokens=100, output_tokens=10))
        self.assertIsNone(usage.result(dict(input=1, output=2, currency="CNY"))["estimated_cost"])
        usage.add(dict(input_tokens=100, output_tokens=10))
        self.assertAlmostEqual(usage.result(dict(input=1, output=2, currency="CNY"))["estimated_cost"], .00024)

    def test_compare_conditions_and_remote_allowlist(self):
        manifest = dict.fromkeys(("dataset_sha256", "config_sha256", "backend", "model", "embedding", "reranker"), "same")
        report = dict(backend="simulated", summary={"full": {"valid": 4, "private": "synthetic-secret", "elapsed_ms": float("inf")},
                                                    "private-label": {"valid": 2}}, prompt="secret-question")
        self.assertEqual(self.comparison.compare(report, report, manifest, manifest)["full"]["valid"]["delta"], 0)
        with self.assertRaises(ValueError):
            self.comparison.compare(report, report, manifest, dict(manifest, backend="other"))
        factory = Mock()
        self.comparison.export(report, replace(settings, langsmith_export_enabled=True, langsmith_api_key="synthetic"), factory)
        payload = factory.return_value.create_run.call_args.kwargs
        self.assertNotIn("private", json.dumps(payload, default=str))
        self.assertEqual(payload["outputs"], {"valid": 4})
        factory.return_value.close.assert_called_once()

    def test_remote_disabled_constructs_no_client(self):
        factory = Mock()
        with self.assertRaises(ValueError):
            self.comparison.export(dict(summary={}), replace(settings, langsmith_export_enabled=False), factory)
        factory.assert_not_called()

    def test_simulated_matrix_preserves_evidence_and_production_policy(self):
        original = (ROOT / "configs/security.json").read_bytes()
        run_dir = asyncio.run(self.runner.run(ROOT / "configs/experiments/security.json", self.root))
        report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        rows = [json.loads(line) for line in (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 77)
        self.assertEqual(report["summary"]["full"]["errors"], 0)
        self.assertEqual(report["summary"]["full"]["unauthorized_retrievals"], 0)
        self.assertEqual(report["summary"]["full"]["synthetic_leaks"], 0)
        self.assertGreater(report["summary"]["framework_only"]["synthetic_leaks"], 0)
        self.assertTrue((run_dir / "manifest.json").is_file())
        self.assertTrue((run_dir / "installed-lock.json").is_file())
        self.assertTrue((run_dir / "source-snapshot/evaluations/security.py").is_file())
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["source_changed_during_run"])
        self.assertEqual((ROOT / "configs/security.json").read_bytes(), original)
