"""按路径缓存短期记忆存储，不在导入时打开数据库。"""
from miniagent.memory.memory_store import MemoryStore


class MemoryContext:
    """数据库路径改变时重建实例，便于测试使用隔离存储。"""

    def __init__(self):
        self._store = None
        self._path = None

    def get_store(self, database_path):
        path = str(database_path)
        if self._store is None or self._path != path:
            self._store = MemoryStore(path)
            self._path = path
        return self._store
