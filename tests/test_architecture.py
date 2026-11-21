"""验证正式包入口与数据根目录，防止旧兼容文件重新进入源码目录。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class ArchitectureTests(unittest.TestCase):
    def test_core_import_does_not_load_ui_or_open_memory(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "untouched.sqlite3"
            environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), MEMORY_DB_PATH=str(database))
            script = (
                "import sys; import miniagent.application.chat; import miniagent.bootstrap; "
                "import miniagent.ui.app; from miniagent.config import settings; "
                "assert 'gradio' not in sys.modules; "
                "assert not settings.memory_db.exists()"
            )
            subprocess.run([sys.executable, "-B", "-c", script], env=environment,
                           check=True, capture_output=True, text=True)

    def test_data_root_and_single_package_layout(self):
        from miniagent import config
        self.assertEqual(config.PROJECT_DIR, ROOT)
        self.assertEqual(config.settings.chroma_dir, ROOT / "data/chroma")
        # 所有实现只有一个来源，禁止遗留的顶层转发模块和重复 Prompt 目录。
        self.assertEqual(list((ROOT / "src").glob("*.py")), [])
        # Git 不跟踪空目录；本机清理受限时允许空壳，但禁止重复的 Prompt 文件。
        self.assertEqual(list((ROOT / "src/prompts").glob("**/*")), [])

    def test_create_app_does_not_initialize_chat_database(self):
        # 页面必须可创建，但历史直到浏览器加载才读取。
        with tempfile.TemporaryDirectory() as temporary:
            environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
                               MEMORY_DB_PATH=str(Path(temporary) / "untouched.sqlite3"))
            script = (
                "from miniagent.ui.app import create_app; "
                "from miniagent.config import settings; "
                "app=create_app(); assert not settings.memory_db.exists(); "
                "assert app is not None"
            )
            subprocess.run([sys.executable, "-B", "-c", script], env=environment,
                           check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
