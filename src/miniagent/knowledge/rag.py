"""Local embeddings through Ollama and a persistent Chroma knowledge base."""
from __future__ import annotations

import math
from pathlib import Path
import re
import threading
import copy

import httpx
import jieba
from rank_bm25 import BM25Plus
from miniagent.config import settings, logger
from miniagent.security.policy import get_policy
from miniagent.knowledge.sources import SUPPORTED_EXTENSIONS, validate_source
from miniagent.knowledge.recycling import RecyclingMixin
from miniagent.knowledge.store import ChromaStoreMixin

# 检索分三阶段：两路召回 → RRF 融合 → 可选重排与阈值过滤。


PROJECT_DIR = settings.project_dir
KNOWLEDGE_DIR = settings.knowledge_dir
CHROMA_DIR = settings.chroma_dir
RRF_K = 60  # 融合只使用各通道名次，避免直接相加不同尺度的原始分数。
DEFAULT_RERANK_THRESHOLD = 0.2  # 合成校准集的初始工作点；真实资料仍需调参，不代表正确率。
_tokenizer = jieba.Tokenizer()
_tokenizer.tmp_dir = str(PROJECT_DIR / ".cache")
_tokenizer.cache_file = "jieba-rag.cache"
_tokenizer_lock = threading.Lock()
_stopwords = {"的", "了", "是", "在", "和", "与", "吗", "呢", "请", "问", "我", "你",
              "什么", "怎么", "如何", "哪些", "根据", "一下", "一个"}


def tokenize(text: str) -> list[str]:
    """中文分词；保留错误码、函数名整体，英文统一小写。"""
    tokens = []
    for part in re.findall(r"[a-zA-Z0-9_]+(?:[./:\-][a-zA-Z0-9_]+)*|[\u3400-\u9fff]+", text):
        if re.fullmatch(r"[\u3400-\u9fff]+", part):
            with _tokenizer_lock:
                (PROJECT_DIR / ".cache").mkdir(exist_ok=True)
                words = list(_tokenizer.cut(part))
            tokens.extend(word for word in words if word.strip() and word not in _stopwords)
        else:
            tokens.append(part.casefold())
    return tokens


class KnowledgeBase(ChromaStoreMixin, RecyclingMixin):
    def __init__(self, db_path=None, knowledge_dir=None, model=None, ollama_url=None, security_policy=None):
        self.knowledge_dir = Path(knowledge_dir or KNOWLEDGE_DIR).resolve()
        self.db_path = Path(db_path or CHROMA_DIR).resolve()
        self.model = model or settings.embedding_model
        self.ollama_url = (ollama_url or settings.ollama_base_url).rstrip("/")
        self._lock = threading.RLock()
        self._collection = None
        self._client = None
        self._bm25_cache = None
        self.security_policy = security_policy if security_policy is not None else get_policy()

    def embed(self, texts: list[str]) -> list[list[float]]:
        """串行调用本地 Ollama；过长输入报错，不静默截断后再生成向量。"""
        vectors = []
        with self._lock, httpx.Client(timeout=180, trust_env=False) as client:
            for start in range(0, len(texts), 8):
                batch = texts[start:start + 8]
                try:
                    response = client.post(f"{self.ollama_url}/api/embed", json={
                        "model": self.model, "input": batch, "truncate": False,
                        "keep_alive": "10m",
                    })
                    response.raise_for_status()
                    result = response.json()["embeddings"]
                except (httpx.HTTPError, KeyError, ValueError) as error:
                    logger.error("Embedding 请求失败，类型=%s", type(error).__name__)
                    raise RuntimeError(
                        f"Ollama 向量生成失败，请确认服务和模型 {self.model} 可用：{error}"
                    ) from error
                if len(result) != len(batch):
                    raise RuntimeError("Ollama 返回的向量数量与输入不一致。")
                for vector in result:
                    norm = math.sqrt(sum(x * x for x in vector))
                    if not norm or not math.isfinite(norm):
                        raise RuntimeError("Ollama 返回了无效向量。")
                    vectors.append([x / norm for x in vector])
        return vectors

    def invalidate_lexical_index(self):
        """资料变化后清除内存 BM25 索引，下次检索再从最新文本构建。"""
        with self._lock:
            self._bm25_cache = None

    def with_policy(self, policy):
        """共享只读 collection 与锁，策略和关键词缓存独立，实验不修改原实例。"""
        scoped = copy.copy(self)
        scoped.security_policy = policy
        scoped._bm25_cache = None
        return scoped

    def _lexical_index(self):
        if self._bm25_cache is None:
            result = self.collection.get(include=["documents", "metadatas"])
            rows = sorted([dict(id=chunk_id, text=text, **meta)
                           for chunk_id, text, meta in zip(
                               result["ids"], result["documents"], result["metadatas"])],
                          key=lambda row: row["id"])
            rows = self.security_policy.filter_hits(rows)
            corpus = [tokenize(row["source"] + " " + row["text"])
                      for row in rows]
            # delta=0：保持正 IDF，但不给完全没有匹配词的文档额外加分。
            index = BM25Plus(corpus, delta=0) if any(corpus) else None
            self._bm25_cache = (rows, index)
        return self._bm25_cache

    def search_candidates(self, query: str, candidate_k: int = 20, mode: str = "hybrid") -> list[dict]:
        """只召回候选；分数相近不代表证据充分，过滤放在 retrieve 中完成。"""
        if mode not in {"hybrid", "vector", "bm25"}:
            raise ValueError("不支持的检索模式。")
        candidate_k = int(candidate_k)
        if not 1 <= candidate_k <= 100:
            raise ValueError("每路候选数量必须在 1–100 之间。")
        if not query.strip():
            return []
        with self._lock:
            count = self.collection.count()
            if not count:
                return []
            merged = {}
            if mode in {"hybrid", "vector"}:
                # 元数据过滤发生在向量召回前，避免拒绝文档占满候选名额。
                allowed = self.security_policy.allowed_sources
                denied = self.security_policy.denied_sources
                if allowed is not None and not allowed:
                    return []
                clauses = []
                if allowed is not None:
                    clauses.append({"source": {"$in": list(allowed)}})
                if denied:
                    clauses.append({"source": {"$nin": list(denied)}})
                source_filter = ({"$and": clauses} if len(clauses) > 1 else clauses[0]) if clauses else None
                result = self.collection.query(
                    query_embeddings=self.embed([query]), n_results=min(candidate_k, count),
                    include=["documents", "metadatas", "distances"],
                    **({"where": source_filter} if source_filter else {}),
                )
                for rank, (chunk_id, text, meta, distance) in enumerate(zip(
                        result["ids"][0], result["documents"][0], result["metadatas"][0],
                        result["distances"][0]), 1):
                    merged[chunk_id] = dict(id=chunk_id, text=text, **meta,
                                            distance=float(distance), similarity=1 - float(distance),
                                            vector_rank=rank, bm25_rank=None, bm25_score=None,
                                            rrf_score=1 / (RRF_K + rank))
            if mode in {"hybrid", "bm25"}:
                rows, index = self._lexical_index()
                terms = tokenize(query)
                if index is not None and terms:
                    scores = index.get_scores(terms)
                    order = sorted((i for i, score in enumerate(scores) if score > 0),
                                   key=lambda i: (-float(scores[i]), rows[i]["id"]))[:candidate_k]
                    for rank, i in enumerate(order, 1):
                        row = rows[i]
                        if row["id"] not in merged:
                            merged[row["id"]] = dict(row, distance=None, similarity=None,
                                                      vector_rank=None, bm25_rank=None,
                                                      bm25_score=None, rrf_score=0.0)
                        hit = merged[row["id"]]
                        hit.update(bm25_rank=rank, bm25_score=float(scores[i]))
                        hit["rrf_score"] += 1 / (RRF_K + rank)
            safe = self.security_policy.filter_hits(merged.values())
            return sorted(safe, key=lambda hit: (-hit["rrf_score"], hit["id"]))

    def search(self, query: str, top_k: int = 4, candidate_k: int = 20,
               mode: str = "hybrid") -> list[dict]:
        top_k = int(top_k)
        if not 1 <= top_k <= 10:
            raise ValueError("最终片段上限必须在 1–10 之间。")
        return self.search_candidates(query, max(top_k, int(candidate_k)), mode)[:top_k]

    def retrieve(self, query: str, top_k=4, candidate_k=20, mode="hybrid",
                 use_rerank=True, threshold=None, rerank_k=20, scorer=None):
        """完整检索入口：保留诊断候选，但只把通过过滤的块交给生成模型。"""
        top_k, rerank_k = int(top_k), int(rerank_k)
        threshold = DEFAULT_RERANK_THRESHOLD if threshold is None else float(threshold)
        if not 1 <= top_k <= 10 or not 1 <= rerank_k <= 100:
            raise ValueError("片段上限须为 1–10，重排候选上限须为 1–100。")
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("重排阈值必须是 0–1 的有限数值。")
        candidates = self.search_candidates(query, max(int(candidate_k), top_k), mode)
        if use_rerank and candidates:
            if scorer is None:
                from miniagent.knowledge.rerank import reranker
                scorer = reranker
            # 仅精排融合后的前 N 个，控制 CPU 延迟；未重排候选不越过过滤进入回答。
            limit = max(top_k, rerank_k)
            ranked = scorer.score(query, candidates[:limit])
            candidates = ranked + candidates[limit:]
            selected = select_context([h for h in ranked if h["rerank_score"] >= threshold], top_k)
        else:
            selected = select_context(candidates, top_k)
        selected_ids = {hit["id"] for hit in selected}
        for hit in candidates:
            if hit["id"] in selected_ids:
                hit["decision"] = "已选入回答"
            elif use_rerank and hit.get("rerank_score") is None:
                hit["decision"] = "未参与重排"
            elif use_rerank and hit["rerank_score"] < threshold:
                hit["decision"] = "低于阈值"
            else:
                hit["decision"] = "超出数量或长度上限"
        logger.info("检索完成，方式=%s，候选=%d，入选=%d，重排=%s", mode, len(candidates), len(selected), use_rerank)
        return {"candidates": candidates, "selected": selected,
                "threshold": threshold if use_rerank else None,
                "use_rerank": use_rerank}

    def snapshot(self):
        """在同一把锁下取得清单和状态，应用层不再读取私有锁。"""
        with self._lock:
            return self.list_documents(), self.status()

    def status(self) -> str:
        with self._lock:
            result = self.collection.get(include=["metadatas"])
        sources = sorted({m["source"] for m in result["metadatas"]})
        return f"知识库：{len(sources)} 个文档，{len(result['ids'])} 个文本块。\n" + "\n".join(sources)

    _validate_source = staticmethod(validate_source)

    def list_documents(self) -> list[dict]:
        """合并向量库与原文件清单，原文缺失或尚未索引的文件也能显示。"""
        with self._lock:
            data = self.collection.get(include=["metadatas"])
            counts = {}
            for metadata in data["metadatas"]:
                name = metadata["source"]
                counts[name] = counts.get(name, 0) + 1
            if self.knowledge_dir.exists():
                for path in self.knowledge_dir.iterdir():
                    if path.suffix.lower() in SUPPORTED_EXTENSIONS and (path.is_file() or path.is_symlink()):
                        counts.setdefault(path.name, 0)
            return [{"source": name, "chunk_count": count,
                     "has_file": (self.knowledge_dir / name).is_file()}
                    for name, count in sorted(counts.items())]




def select_context(candidates: list[dict], top_k: int, max_chars: int = 12000) -> list[dict]:
    """同时限制片段数量和总字符数，避免用户调大 K 后耗尽上下文。"""
    selected, used = [], 0
    for hit in candidates[:top_k]:
        if used + len(hit["text"]) > max_chars:
            break
        selected.append(hit)
        used += len(hit["text"])
    return selected


knowledge_base = KnowledgeBase()
