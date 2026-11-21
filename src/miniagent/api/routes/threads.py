"""会话和旧历史接口，只调用应用已有存储。"""
import asyncio
from miniagent.memory.thread_store import legacy_messages
from fastapi import APIRouter, Request
from miniagent.application.chat_service import BusyError

router = APIRouter()


@router.get("/api/threads")
async def threads(request: Request):
    return {"threads": request.app.state.store.list_threads()}

@router.post("/api/threads", status_code=201)
async def create_thread(request: Request):
    return request.app.state.store.create_thread()

@router.get("/api/threads/{thread_id}/messages")
async def messages(request: Request, thread_id: str):
    return {"messages": request.app.state.store.messages(thread_id)}

@router.delete("/api/threads/{thread_id}")
async def delete_thread(request: Request, thread_id: str):
    if request.app.state.operation_lock.locked():
        raise BusyError("有运行正在进行，请停止后再删除会话。")
    request.app.state.store.delete_thread(thread_id)
    return {"deleted": True}

@router.get("/api/legacy/messages")
async def legacy(request: Request):
    return {"messages": await asyncio.to_thread(legacy_messages, request.app.state.config.memory_db)}
