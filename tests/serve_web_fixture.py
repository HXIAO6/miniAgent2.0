"""浏览器验收专用服务：合成回答、固定 embedding、隔离库，不访问真实模型。"""
import asyncio
from dataclasses import replace
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.api.app import create_app
from miniagent.config import settings
from miniagent.contracts import ChatEvent
from miniagent.knowledge.rag import KnowledgeBase
from miniagent.knowledge.ingest import ingest_file


async def executor(request, dependencies):
    """固定输出用于验证浏览器交互，不能作为真实模型正确率证据。"""
    history = request.history + [{"role": "user", "content": request.message}]
    yield ChatEvent(kind="progress", history=history, status="正在检索本地知识库…")
    if "停止" in request.message:
        yield ChatEvent(kind="progress", history=history, answer="这是尚未完成的部分回答。")
        await asyncio.sleep(60)
    hit = dict(id="fixture", source="星舟维护.md", location="维护；第 1–2 行",
               text="星舟设备冷却液每九天更换一次，更换前关闭设备。", rerank_score=.98, decision="已选入回答")
    yield ChatEvent(kind="progress", history=history,
                   activity={"type": "tool.started", "name": "search_knowledge"})
    await asyncio.sleep(.1)
    yield ChatEvent(kind="progress", history=history, selected=[hit], candidates=[hit], update_scores=True,
                   activity={"type": "tool.completed", "name": "search_knowledge"})
    answer = ""
    for text in ["根据维护手册，", "冷却液每**九天**更换一次", " [资料1]。"]:
        answer += text
        yield ChatEvent(kind="progress", history=history, answer=answer)
        await asyncio.sleep(.1)
    yield ChatEvent(kind="complete", history=history, answer=answer, selected=[hit], candidates=[hit],
                    update_scores=True, persist=True)


if __name__ == "__main__":
    import uvicorn
    output = Path("D:/miniAgent2.0-experiments/web")
    output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="browser-", dir=output))
    config = replace(settings, web_memory_db=root / "web.sqlite3", memory_db=root / "legacy.sqlite3")
    kb = KnowledgeBase(root / "chroma", root / "knowledge")
    kb.embed = lambda texts: [[1., 0.] for _ in texts]
    path = root / "星舟维护.md"
    path.write_text("# 维护\n星舟设备冷却液每九天更换一次，更换前关闭设备。", encoding="utf-8")
    ingest_file(path, kb)
    uvicorn.run(create_app(config, kb, executor=executor, dependency_factory=lambda: None),
                host="127.0.0.1", port=8010)
