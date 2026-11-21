"""显式导出本地统计摘要至 LangSmith；不启用框架自动追踪。"""
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID

from miniagent.config import settings
from miniagent.observability.tracing import TOOLS


def summary_payload(record):
    """重建允许字段，不把本地 JSON 整体上传；即使夹带原文也丢弃。"""
    identifier = str(UUID(record["id"]))
    status = record["status"]
    mode = record["mode"]
    if status not in {"completed", "refusal", "failed", "cancelled", "ignored", "interrupted"} or mode not in {"forced", "auto", "chat"}:
        raise ValueError("运行摘要状态无效。")
    outputs = {key: record[key] for key in ("elapsed_ms", "event_count", "selected_count", "candidate_count")}
    if any(type(value) not in {int, float} or not 0 <= value < 1e12 for value in outputs.values()):
        raise ValueError("运行摘要计数无效。")
    outputs.update(status=status, tools={name: count for name, count in record.get("tools", {}).items()
                                        if name in TOOLS and type(count) is int and 0 <= count <= 10000})
    outputs["security_counts"] = {key: count for key, count in record.get("security_counts", {}).items()
        if key in {stage + "." + outcome for stage in ("ingest", "retrieval", "tool", "output", "workflow")
                   for outcome in ("allowed", "blocked")} and type(count) is int and 0 <= count <= 100000}
    return dict(id=identifier, name="miniagent-summary-v1", run_type="chain", inputs={"mode": mode},
                outputs=outputs, start_time=datetime.fromisoformat(record["started_at"]),
                end_time=datetime.fromisoformat(record["ended_at"]), project_name="miniagent-sanitized")


def export_summary(record, config=None, client_factory=None):
    """仅显式开启后导出；固定项目名，禁止动态模型名/标签夹带私人内容。"""
    config = config or settings
    if not config.langsmith_export_enabled:
        raise ValueError("远程导出未开启，请先配置 MINIAGENT_LANGSMITH_EXPORT=true。")
    endpoint = urlsplit(config.langsmith_endpoint)
    if endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password:
        raise ValueError("LangSmith 地址必须是无凭据的 HTTPS 地址。")
    if not config.langsmith_api_key:
        raise ValueError("缺少 LANGSMITH_API_KEY。")
    payload = summary_payload(record)
    if client_factory is None:
        from langsmith import Client
        client_factory = Client
    client = client_factory(api_url=config.langsmith_endpoint, api_key=config.langsmith_api_key,
                            auto_batch_tracing=False, timeout_ms=3000, omit_traced_runtime_info=True)
    try:
        client.create_run(**payload)
    finally:
        client.close()
