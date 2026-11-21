"""聊天运行接口：HTTP 契约转内部命令，消费结构化事件。"""
import sqlite3
from fastapi.responses import StreamingResponse
from miniagent.api.schemas import RunRequest
from miniagent.api.streaming import encode_events
from miniagent.api.mapping import run_command
from fastapi import APIRouter, Request, HTTPException

router = APIRouter()


@router.get("/api/runs/{run_id}")
async def get_run(request: Request, run_id: str):
    return request.app.state.store.get_run(run_id)

@router.post("/api/runs/{run_id}/cancel")
async def cancel(request: Request, run_id: str):
    return await request.app.state.chat.cancel(run_id)

@router.post("/api/threads/{thread_id}/runs")
async def chat(request: Request, thread_id: str, payload: RunRequest):
    if payload.options.mode == "auto" and request.app.state.config.chat_backend != "langchain":
        raise HTTPException(422, "自动模式需要 LangChain 后端。")
    try:
        run_id, queue = await request.app.state.chat.start(thread_id, run_command(payload))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "此运行 ID 已使用，请刷新历史后重试。")

    return StreamingResponse(encode_events(request.app.state.chat.events(run_id, queue)), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Run-Id": run_id})
