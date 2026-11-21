"""HTTP 输入契约；模型地址、身份、历史和数据库路径均不接受浏览器覆盖。"""
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field, field_validator


class ChatOptions(BaseModel):
    mode: Literal["forced", "auto", "chat"] = "forced"
    only_knowledge: bool = True
    top_k: int = Field(default=4, ge=1, le=10)
    candidate_k: int = Field(default=20, ge=10, le=60)
    retrieval_mode: Literal["hybrid", "vector", "bm25"] = "hybrid"
    use_rerank: bool = True
    rerank_threshold: float = Field(default=.2, ge=0, le=1, allow_inf_nan=False)
    rerank_k: int = Field(default=20, ge=10, le=40)


class RunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    run_id: UUID
    options: ChatOptions = Field(default_factory=ChatOptions)

    @field_validator("message")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("问题不能为空。")
        return value


class DeleteDocuments(BaseModel):
    sources: list[str] = Field(min_length=1, max_length=100)
    confirmed: bool = False
