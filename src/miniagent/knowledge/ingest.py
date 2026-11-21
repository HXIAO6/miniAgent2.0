"""文档入库：解析与分块后，把原文、位置、向量一起保存到本地知识库。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

from miniagent.config import logger
from miniagent.security.policy import get_policy
from miniagent.knowledge.rag import KnowledgeBase, SUPPORTED_EXTENSIONS, knowledge_base
from miniagent.knowledge.parsing import CHUNK_CHARS, OVERLAP_CHARS, extract_sections, validate_chunk_settings, make_chunks

MAX_FILE_BYTES = 30 * 1024 * 1024


def ingest_file(file_path: str | Path, kb: KnowledgeBase = knowledge_base,
                chunk_chars: int = CHUNK_CHARS, overlap_chars: int = OVERLAP_CHARS) -> str:
    chunk_chars, overlap_chars = validate_chunk_settings(chunk_chars, overlap_chars)
    # 内容没变但参数变了，也必须重新索引；配置指纹还用于隔离新旧块 ID。
    profile = hashlib.sha256(json.dumps({"parser_version": 2, "chunk_chars": chunk_chars,
                                         "overlap_chars": overlap_chars}, sort_keys=True).encode()).hexdigest()[:16]
    path = Path(file_path).resolve(strict=True)
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError("仅支持 TXT、Markdown 和有文字层的 PDF。")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("单个文档不能超过 30 MiB。")
    source = path.name
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    # 整份文档检查发生在打开 collection、embedding 和原文件替换之前。
    sections = extract_sections(path)
    policy = getattr(kb, "security_policy", None) or get_policy()
    policy.require_document(source, "\n".join(text for _, text in sections))
    # 入库与召回共享锁，避免查询读取同一文档尚未更新完整的状态。
    with kb.document_transaction() as collection:
        old = collection.get(where={"source": source}, include=["metadatas"])
        if old["ids"] and all(m.get("file_hash") == digest and m.get("index_profile") == profile
                              for m in old["metadatas"]):
            return f"跳过：{source} 内容和分块设置未发生变化（{len(old['ids'])} 块）。"
        chunks = make_chunks(sections, chunk_chars, overlap_chars)
        vectors = kb.embed([chunk["text"] for chunk in chunks])
        kb.knowledge_dir.mkdir(parents=True, exist_ok=True)
        destination = kb.knowledge_dir / source
        if destination.is_symlink() or destination.resolve().parent != kb.knowledge_dir:
            raise ValueError("资料保存路径不安全。")
        # 同名更新先归档旧原文，再替换副本；用户之前的资料仍可恢复。
        if destination.exists() and destination.read_bytes() != raw:
            old_raw = destination.read_bytes()
            archive = kb.knowledge_dir / ".versions" / hashlib.sha256(old_raw).hexdigest()
            archive.mkdir(parents=True, exist_ok=True)
            backup = archive / source
            if not backup.exists():
                backup.write_bytes(old_raw)
        document_key = hashlib.sha256(source.encode()).hexdigest()[:24]
        ids = [f"{document_key}:{digest}:{profile}:{i}" for i in range(len(chunks))]
        added = []
        kb.invalidate_lexical_index()
        try:
            for start in range(0, len(chunks), 64):
                batch = chunks[start:start + 64]
                batch_ids = ids[start:start + 64]
                collection.upsert(
                    ids=batch_ids, embeddings=vectors[start:start + 64],
                    documents=[chunk["text"] for chunk in batch],
                    metadatas=[{"source": source, "file_hash": digest,
                                "index_profile": profile, "chunk_chars": chunk_chars,
                                "overlap_chars": overlap_chars,
                                "location": chunk["location"], "chunk_index": start + i}
                               for i, chunk in enumerate(batch)],
                )
                added.extend(batch_ids)
            fd, temporary = tempfile.mkstemp(dir=kb.knowledge_dir, suffix=".upload")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(raw)
                os.replace(temporary, destination)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        except Exception:
            if added:
                collection.delete(ids=added)
            raise
        obsolete = list(set(old["ids"]) - set(ids))
        # 只有新块写入、原文件保存成功后才清理旧块；同时失效 BM25 缓存。
        if obsolete:
            collection.delete(ids=obsolete)
    return f"已导入：{source}（{len(chunks)} 块）。"


def import_files(paths, chunk_chars: int = CHUNK_CHARS, overlap_chars: int = OVERLAP_CHARS) -> str:
    if not paths:
        return "请先选择资料文件。"
    results = []
    for path in paths:
        try:
            results.append(ingest_file(path, chunk_chars=chunk_chars, overlap_chars=overlap_chars))
            logger.info("文档导入完成")
        except Exception as error:
            logger.error("文档导入失败，类型=%s", type(error).__name__)
            results.append(f"导入失败：{Path(path).name}：{error}")
    return "\n".join(results)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="将指定文档导入本地知识库")
    parser.add_argument("files", nargs="+")
    parser.add_argument("--chunk-chars", type=int, default=CHUNK_CHARS)
    parser.add_argument("--overlap-chars", type=int, default=OVERLAP_CHARS)
    arguments = parser.parse_args()
    print(import_files(arguments.files, arguments.chunk_chars, arguments.overlap_chars))
