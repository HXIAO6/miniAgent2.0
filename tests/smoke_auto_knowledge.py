"""真实第三阶段网页验收；仅导入两份虚构资料，使用原模型和本地检索。"""
import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="auto-knowledge-", dir=output_dir))
    # 模块导入前隔离聊天历史，且显式选用支持工具工作流的新后端。
    os.environ["MEMORY_DB_PATH"] = str(workspace / "memory.sqlite3")
    os.environ["CHAT_BACKEND"] = "langchain"
    from gradio_client import Client
    from miniagent.ui import handlers as app
    from miniagent.knowledge.rag import KnowledgeBase
    from miniagent.knowledge.ingest import ingest_file
    kb = KnowledgeBase(workspace / "chroma", workspace / "knowledge")
    materials = {"星舟维护.md": "# 维护\n星舟设备冷却液每九天更换一次，更换前关闭设备。",
                 "数据备份.md": "# 备份\n配置文件每天凌晨三点备份，保留十四天。"}
    for name, text in materials.items():
        source = workspace / name
        source.write_text(text, encoding="utf-8")
        ingest_file(source, kb)
    app.knowledge_base = kb
    app.settings = replace(app.settings, memory_db=workspace / "memory.sqlite3")
    cases = [
        ("greeting", "你好，请简单打个招呼。", False),
        ("manual", "根据我的星舟维护手册，冷却液多久更换一次？请附来源。", True),
        ("multiple", "我的资料中，星舟冷却液更换周期和配置备份保留时间分别是多少？请附引用。", True),
        ("partial", "我的星舟维护手册中，冷却液多久更换，指定品牌是什么？没有依据的部分请说明。", True),
        ("missing", "我的星舟设备维护资料中，设备重量是多少千克？只回答有资料依据的信息。", True),
    ]
    rows = []
    try:
        app.demo.launch(server_name="127.0.0.1", server_port=7864,
                        prevent_thread_lock=True, inbrowser=False, quiet=True)
        client = Client("http://127.0.0.1:7864", verbose=False)
        with patch.object(kb, "retrieve", wraps=kb.retrieve) as retrieve:
            for case_id, query, should_retrieve in cases:
                before = retrieve.call_count
                result = client.predict(query, [], True, 4, 20, "hybrid", True, .2, 20,
                                        True, "auto", api_name="/predict_with_scores")
                content = app.message_content_to_text(result[1][-1]["content"])
                answer = content.split("</details>", 1)[-1].split("<!-- rag-sources -->", 1)[0]
                calls = retrieve.call_count - before
                assert "发生错误" not in content, content
                assert bool(calls) == should_retrieve, (case_id, calls, answer)
                if should_retrieve:
                    assert 1 <= calls <= app.settings.agent_tool_limit
                if should_retrieve and case_id != "missing":
                    assert "九天" in answer or "9" in answer, answer
                    assert "[资料" in answer and "星舟维护.md" in content, content
                if case_id == "multiple":
                    assert "十四" in answer or "14" in answer, answer
                    assert "数据备份.md" in content, content
                if case_id in {"partial", "missing"}:
                    assert any(word in answer for word in ["未提供", "未说明", "未提及", "没有", "不足", "无法", "未知"]), answer
                rows.append(dict(id=case_id, query=query, answer=answer.strip(), retrieval_calls=calls,
                                 candidates=result[2]["data"], passed=True))
                # 控制台展示问题、回答与调用次数，完整候选诊断仅写入 JSON。
                print(json.dumps({key: rows[-1][key] for key in
                                  ["id", "query", "answer", "retrieval_calls", "passed"]},
                                 ensure_ascii=False), flush=True)
        assert app._get_memory_store().message_count() == 10
        report = dict(materials=materials, model=app.settings.chat_model, backend="langchain",
                      mode="auto", rows=rows, persisted_messages=10,
                      limitations="Small synthetic smoke test; not a security or factual-accuracy benchmark.")
        path = workspace / "report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report: {path}", flush=True)
    finally:
        app.demo.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".cache/phase3")
    main(parser.parse_args().output_dir)
