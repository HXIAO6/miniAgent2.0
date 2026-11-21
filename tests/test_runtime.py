"""配置隔离回归：假密钥、合成片段和 D 盘临时目录，不访问真实模型或资料。"""
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
from miniagent.contracts import ChatDependencies, ChatRequest, ModelEvent
from miniagent.application.chat import stream_chat
from miniagent.runtime import RuntimeEnvironment, bind_environment, current_config
from miniagent.security.policy import SecurityPolicy, get_policy
from miniagent.security.injection import inspect_text
from miniagent.tools.implementations import permitted_functions, get_current_time
from miniagent.observability.decisions import audit


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        parent = Path("D:/miniAgent2.0-experiments/refactor") if sys.platform == "win32" else Path(tempfile.gettempdir())
        parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="runtime-", dir=parent))

    async def test_concurrent_config_policy_and_audit_do_not_cross(self):
        """两个异步请求经线程检查，权限、密钥和审计路径仍分别生效。"""
        async def check(name):
            config = replace(settings, audit_dir=self.root / name, openai_api_key="synthetic-" + name,
                             audit_enabled=True, trace_enabled=False)
            policy = SecurityPolicy(allowed_tools=() if name == "first" else ("get_current_time",))
            with bind_environment(RuntimeEnvironment(config, policy)):
                await asyncio.sleep(0)
                self.assertIs(current_config(), config)
                self.assertIs(get_policy(), policy)
                self.assertIn("configured_secret", await asyncio.to_thread(inspect_text, "synthetic-" + name))
                self.assertNotIn("configured_secret", inspect_text("synthetic-" + ("second" if name == "first" else "first")))
                audit("tool", "allowed", ("get_current_time",))
                return len(permitted_functions()), get_current_time()
        first, second = await asyncio.gather(check("first"), check("second"))
        self.assertEqual(first[0], 0)
        self.assertIn("拒绝", first[1])
        self.assertEqual(second[0], 1)
        self.assertNotIn("拒绝", second[1])
        for name in ("first", "second"):
            self.assertTrue(list((self.root / name).glob("*.jsonl")))

    async def test_pipeline_uses_injected_secret_policy_and_trace_path(self):
        """完整应用入口采用注入密钥审核输出，不落到项目默认追踪目录。"""
        config = replace(settings, openai_api_key="synthetic-runtime-secret", trace_dir=self.root / "trace",
                         audit_dir=self.root / "audit", trace_enabled=True)
        class Backend:
            async def compress_history(self, messages):
                return messages
            async def stream(self, messages, strict=False):
                yield ModelEvent("text", "synthetic-runtime-secret")
        hit = dict(id="safe", source="维护.md", location="合成正文", text="九天更换。")
        kb = Mock()
        kb.retrieve.return_value = dict(selected=[hit], candidates=[hit])
        dependencies = ChatDependencies(kb, None, None, None, Mock(), Backend(), RuntimeEnvironment(config, SecurityPolicy()))
        events = [event async for event in stream_chat(ChatRequest("更换周期"), dependencies)]
        self.assertEqual(events[-1].kind, "refusal")
        self.assertTrue(all("synthetic-runtime-secret" not in event.answer for event in events))
        trace = json.loads(next(config.trace_dir.glob("*.json")).read_text(encoding="utf-8"))
        self.assertEqual(trace["status"], "refusal")
        self.assertEqual(trace["security_counts"]["output.blocked"], 1)

    def test_experiments_and_application_do_not_import_test_helpers(self):
        """静态边界检查防止正式实验重新依赖 patch、tests 或私有执行函数。"""
        for path in (ROOT / "src/miniagent/experiments").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("from unittest.mock", text)
            self.assertNotIn("chat._execute_chat", text)
        service = (ROOT / "src/miniagent/application/chat_service.py").read_text(encoding="utf-8")
        self.assertNotIn("from miniagent.bootstrap", service)
        self.assertNotIn("payload.options", service)

    async def test_api_assembles_custom_policy_and_model_configuration(self):
        """两个入口使用不同策略文件，装配后的工具与模型配置分别生效。"""
        from fastapi.testclient import TestClient
        from miniagent.api.app import create_app
        for name, tools in (("disabled", []), ("clock", ["get_current_time"])):
            root = self.root / name
            root.mkdir()
            policy_path = root / "policy.json"
            policy_path.write_text(json.dumps(dict(allowed_sources=[], denied_sources=[], allowed_tools=tools)), encoding="utf-8")
            config = replace(settings, security_policy_path=policy_path, web_memory_db=root / "web.sqlite3",
                             memory_db=root / "legacy.sqlite3", chroma_dir=root / "chroma", knowledge_dir=root / "knowledge",
                             chat_backend="langchain", chat_model="synthetic-" + name)
            with TestClient(create_app(config)) as client:
                dependencies = client.app.state.chat.dependency_factory()
                self.assertIs(dependencies.backend.settings, config)
                self.assertEqual(len(dependencies.backend.tool_functions), len(tools))
                self.assertEqual(dependencies.environment.policy.allowed_sources, ())
                self.assertEqual(client.get("/api/health").json()["model"], "synthetic-" + name)

    async def test_staging_limit_closes_files_and_preserves_user_original(self):
        """限额失败仅清理本次暂存，不删除上传来源或遗留暂存文件。"""
        from unittest.mock import patch
        from miniagent.application.uploads import staged_uploads, UploadLimitError
        from io import BytesIO
        from starlette.datastructures import UploadFile
        staging = self.root / "staging"
        staging.mkdir()
        original = staging / "original.md"
        original.write_text("原有成果", encoding="utf-8")
        file = UploadFile(BytesIO(b"synthetic-data"), filename="upload.md")
        with patch("miniagent.application.uploads.MAX_FILE_BYTES", 4):
            with self.assertRaises(UploadLimitError):
                async with staged_uploads([file], ["upload.md"], staging):
                    self.fail("超限上传不应交付入库")
        self.assertTrue(file.file.closed)
        self.assertEqual(list(staging.iterdir()), [original])
