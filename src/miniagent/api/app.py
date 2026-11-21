"""本地 FastAPI 应用：结构化会话、SSE 流及受控文档管理，不依赖 Gradio。"""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from miniagent.api.schemas import DeleteDocuments, RunRequest
from miniagent.application.chat_service import BusyError, ChatService
from miniagent.application.documents import DocumentService
from miniagent.config import settings as default_settings
from miniagent.knowledge.ingest import MAX_FILE_BYTES, validate_chunk_settings
from miniagent.knowledge.rag import KnowledgeBase
from miniagent.memory.thread_store import ThreadStore, legacy_messages


def create_app(settings=None, knowledge_base=None, store=None, executor=None, dependency_factory=None):
    """运行时注入配置及隔离实现；导入模块不会打开数据库或创建 collection。"""
    settings = settings or default_settings

    @asynccontextmanager
    async def lifespan(app):
        app.state.operation_lock = asyncio.Lock()
        app.state.kb = knowledge_base or KnowledgeBase(settings.chroma_dir, settings.knowledge_dir)
        app.state.store = store or ThreadStore(settings.web_memory_db)
        app.state.store.recover()
        extra = {"executor": executor} if executor is not None else {}
        app.state.chat = ChatService(settings, app.state.kb, app.state.store,
                                     app.state.operation_lock, dependency_factory=dependency_factory, **extra)
        yield
        await app.state.chat.close()

    app = FastAPI(title="MiniAgent API", version="1.0", lifespan=lifespan)

    @app.middleware("http")
    async def local_browser_guard(request, call_next):
        # 同源生产部署及 Vite 本机代理可访问；阻止其他网站在浏览器中直接发起变更。
        origin = request.headers.get("origin")
        allowed = {str(request.base_url).rstrip("/"), "http://127.0.0.1:5173", "http://localhost:5173"}
        if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in allowed:
            return JSONResponse({"detail": "不允许的请求来源。"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"detail": "会话或运行不存在。"}, status_code=404)

    @app.exception_handler(BusyError)
    async def busy(request, error):
        return JSONResponse({"detail": str(error)}, status_code=409)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "backend": settings.chat_backend, "model": settings.chat_model,
                "capabilities": {"cancel": True, "sources": True, "approval": False}}

    @app.get("/api/threads")
    async def threads():
        return {"threads": app.state.store.list_threads()}

    @app.post("/api/threads", status_code=201)
    async def create_thread():
        return app.state.store.create_thread()

    @app.get("/api/threads/{thread_id}/messages")
    async def messages(thread_id: str):
        return {"messages": app.state.store.messages(thread_id)}

    @app.delete("/api/threads/{thread_id}")
    async def delete_thread(thread_id: str):
        if app.state.operation_lock.locked():
            raise BusyError("有运行正在进行，请停止后再删除会话。")
        app.state.store.delete_thread(thread_id)
        return {"deleted": True}

    @app.get("/api/legacy/messages")
    async def legacy():
        return {"messages": await asyncio.to_thread(legacy_messages, settings.memory_db)}

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str):
        return app.state.store.get_run(run_id)

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel(run_id: str):
        return await app.state.chat.cancel(run_id)

    @app.post("/api/threads/{thread_id}/runs")
    async def chat(thread_id: str, payload: RunRequest):
        if payload.options.mode == "auto" and settings.chat_backend != "langchain":
            raise HTTPException(422, "自动模式需要 LangChain 后端。")
        try:
            run_id, queue = await app.state.chat.start(thread_id, payload)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "此运行 ID 已使用，请刷新历史后重试。")

        async def event_stream():
            async for event in app.state.chat.events(run_id, queue):
                if event is None:
                    yield ": keepalive\n\n"
                else:
                    # 每条 JSON 独占 data 行，正文中的换行由 JSON 转义，支持按序处理。
                    yield f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        return StreamingResponse(event_stream(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "X-Run-Id": run_id})

    @app.get("/api/documents")
    async def documents():
        documents, status = await DocumentService(app.state.kb).snapshot()
        return {"documents": documents, "status": status}

    @app.post("/api/documents/upload")
    async def upload(files: list[UploadFile] = File(...), chunk_chars: int = Form(1200), overlap_chars: int = Form(180)):
        if not 1 <= len(files) <= 8:
            raise HTTPException(422, "一次可上传 1–8 份资料。")
        try:
            validate_chunk_settings(chunk_chars, overlap_chars)
            names = [file.filename or "" for file in files]
            for name in names:
                app.state.kb._validate_source(name)
            if len(set(names)) != len(names):
                raise ValueError("一次上传不可包含同名文件。")
        except ValueError as error:
            raise HTTPException(422, str(error))
        if app.state.operation_lock.locked():
            raise BusyError("回答或资料操作进行中，请稍后再上传。")
        async with app.state.operation_lock:
            # 上传原件暂存于项目缓存，逐块限制大小，不把任意客户端路径交给入库函数。
            staging = settings.project_dir / ".cache" / "uploads"
            staging.mkdir(parents=True, exist_ok=True)
            temporary = Path(tempfile.mkdtemp(prefix="upload-", dir=staging))
            try:
                paths, total = [], 0
                for file, name in zip(files, names):
                    path, size = temporary / name, 0
                    with path.open("wb") as target:
                        while block := await file.read(1024 * 1024):
                            size += len(block)
                            total += len(block)
                            if size > MAX_FILE_BYTES or total > 64 * 1024 * 1024:
                                raise HTTPException(413, "单文件上限 30 MiB，一次上传总量上限 64 MiB。")
                            target.write(block)
                    paths.append(path)
                result = await DocumentService(app.state.kb).upload(paths, chunk_chars, overlap_chars)
                return {"result": result}
            finally:
                for file in files:
                    await file.close()
                # 只清理当前请求由 mkdtemp 创建的暂存目录，不删除知识库或用户原件。
                shutil.rmtree(temporary)

    @app.post("/api/documents/delete")
    async def delete_documents(payload: DeleteDocuments):
        if not payload.confirmed:
            raise HTTPException(422, "请明确确认待删除资料。")
        if app.state.operation_lock.locked():
            raise BusyError("回答或资料操作进行中，请稍后再删除。")
        async with app.state.operation_lock:
            return {"result": await DocumentService(app.state.kb).delete(payload.sources, confirmed=True)}

    # 构建后的 React 与 API 同源，不要求 Node.js 在生产运行时常驻。
    frontend = settings.project_dir / "frontend" / "dist"
    if frontend.is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    else:
        @app.get("/", include_in_schema=False)
        async def frontend_missing():
            return {"message": "前端尚未构建，请按 README 执行 npm run build；接口文档位于 /docs。"}
    return app


def launch():
    """默认仅监听回环地址，当前版本为个人本机应用，不提供公网认证。"""
    import uvicorn
    uvicorn.run(create_app(), host=default_settings.host, port=default_settings.api_port)
