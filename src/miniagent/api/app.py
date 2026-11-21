"""本地 FastAPI 应用：结构化会话、SSE 流及受控文档管理，不依赖 Gradio。"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from miniagent.application.chat_service import BusyError
from miniagent.bootstrap import build_chat_service
from miniagent.api.routes import chat, threads, documents
from miniagent.security.policy import load_policy
from miniagent.runtime import RuntimeEnvironment
from miniagent.application.documents import DocumentService
from miniagent.config import settings as default_settings
from miniagent.knowledge.rag import KnowledgeBase
from miniagent.memory.thread_store import ThreadStore


def create_app(settings=None, knowledge_base=None, store=None, executor=None, dependency_factory=None):
    """运行时注入配置及隔离实现；导入模块不会打开数据库或创建 collection。"""
    settings = settings or default_settings

    @asynccontextmanager
    async def lifespan(app):
        app.state.config = settings
        app.state.operation_lock = asyncio.Lock()
        policy = load_policy(str(settings.security_policy_path))
        app.state.environment = RuntimeEnvironment(settings, policy)
        app.state.kb = knowledge_base or KnowledgeBase(settings.chroma_dir, settings.knowledge_dir,
            model=settings.embedding_model, ollama_url=settings.ollama_base_url, security_policy=policy)
        app.state.documents = DocumentService(app.state.kb, app.state.environment)
        app.state.store = store or ThreadStore(settings.web_memory_db)
        app.state.store.recover()
        app.state.chat = build_chat_service(settings, app.state.kb, app.state.store,
                                     app.state.operation_lock, dependency_factory=dependency_factory, executor=executor)
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
                "capabilities": {"cancel": True, "sources": True, "approval": False,
                                 "output_review": True, "token_stream_before_review": False}}

    for router in (threads.router, chat.router, documents.router):
        app.include_router(router)

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
    from miniagent.config import configure_logging
    configure_logging(default_settings)
    uvicorn.run(create_app(), host=default_settings.host, port=default_settings.api_port)
