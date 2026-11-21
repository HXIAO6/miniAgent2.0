"""离线基线：合成向量验证检索机制，固定模型输出比较新旧聊天入口。

不访问模型服务或正式数据。该报告不衡量语义模型质量、答案准确率或攻击成功率。
"""
import argparse
import asyncio
from dataclasses import replace
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def fixture_embeddings(texts):
    """哈希词袋仅用于确定性回归，不能冒充 BGE-M3 的真实语义效果。"""
    from miniagent.knowledge.rag import tokenize
    vectors = []
    for text in texts:
        vector = [0.0] * 64
        for token in tokenize(text):
            bucket = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % 64
            vector[bucket] += 1.0
        norm = sum(value * value for value in vector) ** .5 or 1.0
        vectors.append([value / norm for value in vector])
    return vectors


class FixedRun:
    """替代外部 SDK 网络请求，确保比较的是流程变化而非模型随机性。"""
    def __init__(self, text):
        self.text = text

    async def stream_events(self):
        yield SimpleNamespace(type="raw_response_event", data=SimpleNamespace(
            type="response.output_text.delta", delta=self.text))


def run(output_dir):
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="baseline-", dir=output_dir))
    # 必须在导入界面和配置前设置，旧入口的导入初始化也只能接触隔离数据库。
    os.environ["MEMORY_DB_PATH"] = str(workspace / "memory.sqlite3")
    # 固定旧 SDK 输出的基线不能意外改为真实 LangChain 调用。
    os.environ["CHAT_BACKEND"] = "openai-agents"
    from miniagent.knowledge.ingest import ingest_file
    from miniagent.knowledge.rag import KnowledgeBase
    fixture_path = ROOT / "tests/fixtures/retrieval_cases.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    kb = KnowledgeBase(workspace / "chroma", workspace / "knowledge")
    kb.embed = fixture_embeddings
    for document in fixture["documents"]:
        source = workspace / document["source"]
        source.write_text(document["text"], encoding="utf-8")
        ingest_file(source, kb)
    retrieval = []
    for mode in ["vector", "bm25", "hybrid"]:
        for question in fixture["questions"]:
            hits = kb.search_candidates(question["query"], 20, mode)
            retrieval.append(dict(id=question["id"], mode=mode,
                ranked_ids=[hit["id"] for hit in hits],
                sources=[hit["source"] for hit in hits[:4]]))

    from miniagent.ui import handlers as app
    app.settings = replace(app.settings, memory_db=workspace / "memory.sqlite3")
    chat = []
    async def collect(message, use_knowledge, hits, reply):
        with patch.object(app.knowledge_base, "retrieve", return_value=dict(candidates=hits, selected=hits)), \
             patch.object(app.Runner, "run_streamed", return_value=FixedRun(reply)) as model:
            results = [item async for item in app.predict(message, [], use_knowledge, show_scores=True)]
        final = results[-1]
        # 耗时和运行 ID 不属于功能契约；保留回答、引用和实际模型调用次数。
        content = final[1][-1]["content"].split("</details>", 1)[-1]
        return dict(content=content, model_calls=model.call_count,
                    scores=final[2] if len(final) == 3 else [])
    async def chat_cases():
        hit = dict(id="fixture", source="星舟维护.md", location="正文", text="冷却液每九天更换。")
        for case_id, use_knowledge, hits, reply in [
            ("answer", True, [hit], "九天[资料1]。"),
            ("invalid_citation", True, [hit], "错误编号[资料9]。"),
            ("refusal", True, [], "不应调用模型"),
            ("normal_chat", False, [], "你好。"),
        ]:
            row = await collect(case_id, use_knowledge, hits, reply)
            chat.append(dict(id=case_id, **row))
    asyncio.run(chat_cases())
    report = dict(
        schema_version=1, backend="openai-agents-fixed-output",
        embedding="deterministic-hash-bag-of-words-64-not-bge-m3",
        fixture_sha256=hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        python=platform.python_version(),
        dependencies={name: importlib.metadata.version(name) for name in
                      ["openai-agents", "chromadb", "gradio", "onnxruntime"]},
        # 目录迁移后记录真实实现的哈希，不能只记录几行兼容入口。
        source_sha256={name: hashlib.sha256((ROOT / "src/miniagent" / relative).read_bytes()).hexdigest()
                       for name, relative in {
                           "rag.py": "knowledge/rag.py", "ingest.py": "knowledge/ingest.py",
                           "rerank.py": "knowledge/rerank.py", "memory_store.py": "memory/memory_store.py",
                       }.items()},
        retrieval=retrieval, chat=chat, persisted_message_count=app._get_memory_store().message_count(),
        limitations="Synthetic mechanics and fixed-output compatibility only; no live LLM or embedding quality assessment.")
    report_path = workspace / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report_path)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".cache/phase1")
    parser.add_argument("--compare", type=Path, help="对照已有 report.json 的功能结果")
    args = parser.parse_args()
    current = run(args.output_dir)
    if args.compare:
        previous = json.loads(args.compare.read_text(encoding="utf-8"))
        for key in ["fixture_sha256", "source_sha256", "retrieval", "chat", "persisted_message_count"]:
            if current[key] != previous[key]:
                raise SystemExit(f"Baseline differs: {key}")
        print("Baseline comparison: PASS")
