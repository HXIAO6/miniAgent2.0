"""新 HTTP 服务真实联调：隔离合成库 + 现有 DeepSeek/Ollama/ONNX，不读正式资料。"""
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from fastapi.testclient import TestClient
from miniagent.api.app import create_app
from miniagent.config import settings
from miniagent.knowledge.rag import KnowledgeBase
from miniagent.knowledge.ingest import ingest_file


def main():
    output = Path("D:/miniAgent2.0-experiments/web")
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="live-api-", dir=output))
    config = replace(settings, web_memory_db=root / "web.sqlite3", memory_db=root / "legacy.sqlite3",
                     chat_backend="langchain")
    kb = KnowledgeBase(root / "chroma", root / "knowledge")
    materials = {"星舟维护.md": "# 维护\n星舟设备冷却液每九天更换一次，更换前关闭设备。",
                 "数据备份.md": "# 备份\n配置文件每天凌晨三点备份，保留十四天。"}
    for name, text in materials.items():
        source = root / name
        source.write_text(text, encoding="utf-8")
        ingest_file(source, kb)
    rows = []
    with TestClient(create_app(config, kb)) as client:
        thread_id = client.post("/api/threads").json()["id"]
        for case_id, question, mode in [
            ("forced", "根据维护手册，星舟冷却液多久更换？请附引用。", "forced"),
            ("refusal", "月球背面陨石坑如何命名？", "forced"),
            ("auto", "我的资料中配置文件备份能保留多少天？请附来源。", "auto"),
        ]:
            run_id = str(uuid.uuid4())
            response = client.post(f"/api/threads/{thread_id}/runs", json={
                "message": question, "run_id": run_id, "options": {"mode": mode},
            })
            assert response.status_code == 200, response.text
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
            assert events[-1]["type"] == "run.completed", events[-1]
            message = events[-1]["data"]["message"]
            answer = message["content"]
            if case_id == "forced":
                assert "九天" in answer or "9" in answer, answer
                assert message["metadata"]["sources"][0]["source"] == "星舟维护.md"
                assert "[资料1]" in answer
            elif case_id == "refusal":
                assert message["metadata"]["status"] == "refusal"
                assert "没有找到足够相关" in answer
            else:
                assert "十四" in answer or "14" in answer, answer
                assert any(event["type"] == "tool.completed" for event in events)
                assert any(source["source"] == "数据备份.md" for source in message["metadata"]["sources"])
            rows.append(dict(id=case_id, question=question, mode=mode, answer=answer,
                             event_types=[event["type"] for event in events], passed=True))
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        assert len(client.get(f"/api/threads/{thread_id}/messages").json()["messages"]) == 6
    path = root / "report.json"
    path.write_text(json.dumps(dict(materials=materials, rows=rows, persisted_messages=6), ensure_ascii=False, indent=2), encoding="utf-8")
    print(path, flush=True)


if __name__ == "__main__":
    main()
