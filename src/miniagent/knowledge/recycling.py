"""文档删除、快照和回滚事务；复用原逻辑，不改变回收目录与快照格式。"""
import json
import os
from datetime import datetime, timezone
import uuid
from miniagent.config import logger


class RecyclingMixin:
    """供知识库入口复用的回收实现，共享原锁和 collection。"""

    def delete_document(self, source: str) -> dict:
        """从检索库移除文档，原文与索引快照保留在回收站，失败时尽量回滚。"""
        self._validate_source(source)
        with self._lock:
            if source not in {row["source"] for row in self.list_documents()}:
                raise ValueError("该文档已不在知识库列表中，请刷新后重试。")
            original = self.knowledge_dir / source
            # 禁止通过链接或目录跳转移动知识库外部的文件。
            if original.is_symlink() or original.resolve() != original or (original.exists() and not original.is_file()):
                raise ValueError("原文件路径异常，未执行删除。")
            trash_root = self.db_path.parent / "trash"
            if trash_root.resolve() != trash_root or trash_root.is_symlink():
                raise ValueError("回收站路径异常，未执行删除。")
            trash_root.mkdir(parents=True, exist_ok=True)
            batch = trash_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex)
            batch.mkdir()
            # Chroma 与文件系统没有跨库事务；先持久化完整快照，确保异常时仍有恢复材料。
            snapshot = self.collection.get(where={"source": source},
                                           include=["documents", "metadatas", "embeddings"])
            vectors = snapshot["embeddings"]
            snapshot_data = {"ids": snapshot["ids"], "documents": snapshot["documents"],
                             "metadatas": snapshot["metadatas"],
                             "embeddings": vectors.tolist() if hasattr(vectors, "tolist") else vectors}
            record = {"source": source, "state": "prepared", "original_path": str(original),
                      "chunk_count": len(snapshot["ids"]), "snapshot": snapshot_data}
            manifest = batch / "manifest.json"

            def save_record():
                temporary = batch / "manifest.json.tmp"
                temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
                os.replace(temporary, manifest)

            save_record()
            recycled = batch / source
            moved = False
            db_attempted = False
            try:
                # 先移动原文；若文件被占用，数据库仍保持原样。
                if original.exists():
                    original.rename(recycled)
                    moved = True
                self.invalidate_lexical_index()
                if snapshot["ids"]:
                    db_attempted = True
                    self.collection.delete(ids=snapshot["ids"])
                    if self.collection.get(where={"source": source}, include=[])["ids"]:
                        raise RuntimeError("向量库仍存在该文档的记录。")
                record["state"] = "deleted"
                save_record()
            except Exception as error:
                logger.error("文档删除失败，开始回滚，类型=%s", type(error).__name__)
                # 删除调用可能已经部分生效，因此只要尝试过就恢复快照；BM25 下次读取最新库。
                rollback_errors = []
                if db_attempted:
                    try:
                        for start in range(0, len(snapshot["ids"]), 64):
                            self.collection.upsert(**{key: value[start:start + 64]
                                for key, value in snapshot_data.items()})
                    except Exception as rollback_error:
                        rollback_errors.append(f"索引恢复失败：{rollback_error}")
                if moved:
                    try:
                        if original.exists():
                            raise RuntimeError("原路径已被占用，保留回收站原文，避免覆盖。")
                        recycled.rename(original)
                    except Exception as rollback_error:
                        rollback_errors.append(f"原文恢复失败：{rollback_error}")
                self.invalidate_lexical_index()
                record["state"] = "rollback_failed" if rollback_errors else "rolled_back"
                record["error"] = str(error)
                record["rollback_errors"] = rollback_errors
                try:
                    save_record()
                except Exception as record_error:
                    rollback_errors.append(f"状态写入失败：{record_error}")
                detail = "；".join(rollback_errors) if rollback_errors else "原文与索引已恢复"
                logger.warning("删除回滚结果=%s", record["state"])
                raise RuntimeError(f"删除失败：{error}；{detail}。恢复材料：{batch}") from error
            logger.info("文档删除完成，移除块数=%d，原文件回收=%s", len(snapshot["ids"]), moved)
            return {"source": source, "chunk_count": len(snapshot["ids"]),
                    "file_recycled": moved, "trash_path": str(batch)}
