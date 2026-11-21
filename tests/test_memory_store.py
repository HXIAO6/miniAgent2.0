"""SQLite 短期记忆持久化与事务测试。"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.memory.memory_store import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        (ROOT / ".cache").mkdir(exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="memory-tests-", dir=ROOT / ".cache"))

    def test_reopen_preserves_messages_and_order(self):
        database = self.root / "memory.sqlite3"
        store = MemoryStore(database)
        store.append_turn("你好", "你好，有什么可以帮你？")
        store.append_turn("第二个问题", "第二个回答")
        reopened = MemoryStore(database)
        self.assertEqual(reopened.load_messages(), [
            {"role": "user", "content": "你好"},
            {"role": "assistant", "content": "你好，有什么可以帮你？"},
            {"role": "user", "content": "第二个问题"},
            {"role": "assistant", "content": "第二个回答"},
        ])
        self.assertEqual(reopened.message_count(), 4)

    def test_append_turn_is_atomic_and_clear_keeps_database(self):
        store = MemoryStore(self.root / "memory.sqlite3")
        store.append_turn("问题", "回答")
        self.assertEqual(store.message_count(), 2)
        store.append_turn("", "不应写入")
        self.assertEqual(store.message_count(), 2)
        store.clear()
        self.assertEqual(store.message_count(), 0)
        self.assertTrue((self.root / "memory.sqlite3").exists())
        self.assertTrue((self.root / "memory.sqlite3").is_file())


if __name__ == "__main__":
    unittest.main()
