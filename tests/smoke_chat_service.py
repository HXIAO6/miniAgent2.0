"""真实 Gradio 聊天接口 + 固定 SDK 输出，验证服务与界面之间的适配。

不调用外部模型，数据库在导入界面前切换到隔离目录，避免触及正式历史。
"""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


class FixedRun:
    async def stream_events(self):
        for text in ["九天", "[资料1]。"]:
            yield SimpleNamespace(type="raw_response_event", data=SimpleNamespace(
                type="response.output_text.delta", delta=text))


def main():
    (ROOT / ".cache").mkdir(exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="chat-ui-smoke-", dir=ROOT / ".cache"))
    os.environ["MEMORY_DB_PATH"] = str(root / "memory.sqlite3")
    # 延迟导入：原入口仍会初始化页面历史，必须先配置隔离的存储路径。
    from gradio_client import Client
    import knowledge_assistant as app
    from rag import KnowledgeBase
    app.knowledge_base = KnowledgeBase(root / "chroma", root / "knowledge")
    hit = dict(id="fixture", source="合成维护.md", location="正文", text="冷却液每九天更换。")
    with patch.object(app.knowledge_base, "retrieve", return_value=dict(candidates=[hit], selected=[hit])) as retrieve, \
         patch.object(app.Runner, "run_streamed", return_value=FixedRun()) as model:
        try:
            app.demo.launch(server_name="127.0.0.1", server_port=7863,
                            prevent_thread_lock=True, inbrowser=False, quiet=True)
            client = Client("http://127.0.0.1:7863", verbose=False)
            def ask():
                return client.predict("多久更换？", [], True, 4, 20, "hybrid",
                                      True, .2, 20, True, api_name="/predict_with_scores")
            answered = ask()
            final = app.message_content_to_text(answered[1][-1]["content"])
            assert "九天[资料1]" in final and "合成维护.md" in final, final
            assert answered[2]["data"][0][1] == "资料1"
            assert model.call_count == 1
            retrieve.return_value = dict(candidates=[], selected=[])
            refused = ask()
            refusal = app.message_content_to_text(refused[1][-1]["content"])
            assert "没有找到足够相关" in refusal, refusal
            assert model.call_count == 1, "拒答不应调用模型"
            stored = app._get_memory_store().load_messages()
            assert len(stored) == 4
            assert stored[-1]["content"] == refusal
            result = dict(answer=True, citations=True, scores=True, refusal=True,
                          persisted_messages=len(stored), external_model_calls=0)
            (root / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print("Chat UI adapter and SQLite persistence: OK", flush=True)
            print(root / "report.json", flush=True)
        finally:
            app.demo.close()


if __name__ == "__main__":
    main()
