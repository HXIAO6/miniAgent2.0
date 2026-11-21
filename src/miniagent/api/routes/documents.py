"""资料接口：校验 HTTP 输入和上传限额，入库与回收委托文档服务。"""
from fastapi import File, Form, UploadFile
from miniagent.api.schemas import DeleteDocuments
from miniagent.knowledge.parsing import validate_chunk_settings
from miniagent.application.uploads import staged_uploads, UploadLimitError
from miniagent.knowledge.sources import validate_source
from fastapi import APIRouter, Request, HTTPException
from miniagent.application.chat_service import BusyError

router = APIRouter()


@router.get("/api/documents")
async def documents(request: Request):
    documents, status = await request.app.state.documents.snapshot()
    return {"documents": documents, "status": status}

@router.post("/api/documents/upload")
async def upload(request: Request, files: list[UploadFile] = File(...), chunk_chars: int = Form(1200), overlap_chars: int = Form(180)):
    if not 1 <= len(files) <= 8:
        raise HTTPException(422, "一次可上传 1–8 份资料。")
    try:
        validate_chunk_settings(chunk_chars, overlap_chars)
        names = [file.filename or "" for file in files]
        for name in names:
            validate_source(name)
        if len(set(names)) != len(names):
            raise ValueError("一次上传不可包含同名文件。")
    except ValueError as error:
        raise HTTPException(422, str(error))
    if request.app.state.operation_lock.locked():
        raise BusyError("回答或资料操作进行中，请稍后再上传。")
    async with request.app.state.operation_lock:
        # 上传原件暂存于项目缓存，逐块限制大小，不把任意客户端路径交给入库函数。
        staging = request.app.state.config.project_dir / ".cache" / "uploads"
        try:
            async with staged_uploads(files, names, staging) as paths:
                result = await request.app.state.documents.upload(paths, chunk_chars, overlap_chars)
                return {"result": result}
        except UploadLimitError as error:
            raise HTTPException(413, str(error))

@router.post("/api/documents/delete")
async def delete_documents(request: Request, payload: DeleteDocuments):
    if not payload.confirmed:
        raise HTTPException(422, "请明确确认待删除资料。")
    if request.app.state.operation_lock.locked():
        raise BusyError("回答或资料操作进行中，请稍后再删除。")
    async with request.app.state.operation_lock:
        return {"result": await request.app.state.documents.delete(payload.sources, confirmed=True)}
