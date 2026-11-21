"""Chroma 延迟存储装配与文档事务锁，保留原 collection 和元数据格式。"""
from contextlib import contextmanager
import chromadb
from chromadb.config import Settings


class ChromaStoreMixin:
    """知识库持久化实现，与召回和重排算法分开维护。"""

    @property
    def collection(self):
        with self._lock:
            if self._collection is None:
                self.db_path.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=str(self.db_path), settings=Settings(anonymized_telemetry=False)
                )
                collection = self._client.get_or_create_collection(
                    name="documents_v1", embedding_function=None,
                    metadata={"embedding_model": self.model, "pipeline_version": "1"},
                    configuration={"hnsw": {"space": "cosine"}},
                )
                if collection.metadata.get("embedding_model") != self.model:
                    raise ValueError("向量库使用了其他 embedding 模型，请使用独立的新向量库目录。")
                self._collection = collection
            return self._collection

    @contextmanager
    def document_transaction(self):
        """公开的入库事务边界，不要求调用者读取私有锁。"""
        with self._lock:
            yield self.collection
