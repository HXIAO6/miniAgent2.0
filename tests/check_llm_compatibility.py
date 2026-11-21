"""真实模型兼容性检查：仅发送合成文本，不读取个人知识库或执行文件工具。"""
import asyncio
from datetime import datetime
import importlib.metadata
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from miniagent.config import settings
from miniagent.adapters.llm import LangChainBackend, build_model, load_prompt


def synthetic_clock() -> str:
    """返回固定的合成测试时刻，不访问文件或网络。"""
    return "2099-01-01 12:34:56"


async def main():
    from langsmith import tracing_context
    output = Path("D:/miniAgent2.0-experiments/phase2")
    output.mkdir(parents=True, exist_ok=True)
    rows = []
    with tracing_context(enabled=False):
        # 普通非流式调用验证 Chat Completions 地址和模型名与旧配置兼容。
        model = build_model(settings, settings.chat_model)
        result = await model.ainvoke("这是合成兼容性测试，请只回复：兼容成功")
        assert "兼容成功" in result.content, result.content
        rows.append(dict(id="invoke", result=result.content, passed=True))

        backend = LangChainBackend(settings)
        events = [event async for event in backend.stream([
            {"role": "user", "content": "合成资料：星舟设备冷却液每九天更换一次。问题：周期是多少？请简短回答。"}
        ], strict=True)]
        answer = "".join(event.text for event in events if event.kind == "text")
        assert "九天" in answer or "9" in answer, answer
        rows.append(dict(id="stream", result=answer, text_events=sum(event.kind == "text" for event in events), passed=True))

        messages = [dict(role="user" if index % 2 == 0 else "assistant",
                         content="合成计划：研究虚构的星舟设备，冷却周期九天。") for index in range(32)]
        compressed = await backend.compress_history(messages)
        assert len(compressed) == 9 and compressed[1:] == messages[-8:]
        assert compressed[0]["role"] == "user"
        rows.append(dict(id="summary", result=compressed[0]["content"], retained=8, passed=True))

        # 模型获得的唯一工具是固定时钟；无需读取本机时间、个人文件或实际联网搜索。
        tool_backend = LangChainBackend(settings, [synthetic_clock])
        events = [event async for event in tool_backend.stream([
            {"role": "user", "content": "请调用 synthetic_clock 工具取得合成测试时间，并原样回复工具返回的时间。不要猜测。"}
        ])]
        answer = "".join(event.text for event in events if event.kind == "text")
        assert any(event.kind == "tool" and event.text == "synthetic_clock" for event in events), answer
        assert "2099-01-01" in answer and "12:34:56" in answer, answer
        rows.append(dict(id="tool_call", result=answer, tool="synthetic_clock", passed=True))

    report = dict(timestamp=datetime.now().isoformat(), model=settings.chat_model,
                  backend="langchain", materials="synthetic manual, repeated synthetic history, fixed clock",
                  dependencies={name: importlib.metadata.version(name) for name in
                                ["langchain", "langchain-openai", "langchain-core", "langgraph", "langsmith"]},
                  cases=rows, limitations="Small compatibility smoke test, not security or answer-accuracy evaluation.")
    path = output / "live-compatibility.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rows, ensure_ascii=False, indent=2), flush=True)
    print(path, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
