"""仅记录固定字段的运行摘要；不采集问题、回答、来源名称、工具参数或异常正文。"""
import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import uuid

from miniagent.config import logger, settings
from miniagent.runtime import current_config

_current = ContextVar("miniagent_trace", default=None)
TOOLS = {"get_current_time", "search_knowledge", "search_web", "read_local_file", "write_local_file"}


def security_decision(stage, outcome):
    """同一请求中的同步检索线程继承上下文，只累计数量，不保存命中原文。"""
    record = _current.get()
    if record is not None and stage in {"ingest", "retrieval", "tool", "output", "workflow"}:
        key = stage + "." + ("blocked" if outcome == "blocked" else "allowed")
        record["security_counts"][key] = record["security_counts"].get(key, 0) + 1


def _write(record, directory):
    """每轮独立 UUID 文件，原子替换，避免并发追加 JSONL 产生半行。"""
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    path = root / (record["id"] + ".json")
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


async def observed_events(events, request, config=None):
    """包裹真实应用事件；正常、失败、取消均收尾，追踪写入失败不破坏聊天。"""
    config = config or current_config(settings)
    if not config.trace_enabled:
        async for event in events:
            yield event
        return
    record = dict(schema_version=1, id=str(uuid.uuid4()), started_at=datetime.now(timezone.utc).isoformat(),
                  mode="auto" if request.use_knowledge and request.knowledge_mode == "auto" else
                  "forced" if request.use_knowledge else "chat", status="interrupted",
                  elapsed_ms=0, event_count=0, selected_count=0, candidate_count=0,
                  tools={}, security_counts={})
    start = time.monotonic()
    iterator = events.__aiter__()
    saved = False
    async def save():
        nonlocal saved
        if saved:
            return
        saved = True
        record["elapsed_ms"] = round((time.monotonic() - start) * 1000, 3)
        record["ended_at"] = datetime.now(timezone.utc).isoformat()
        try:
            await asyncio.shield(asyncio.to_thread(_write, record, config.trace_dir))
        except Exception:
            logger.warning("运行摘要写入失败；聊天结果不受影响。")
    try:
        while True:
            # 不跨 yield 保留 token，消费者提前结束时也不会跨上下文 reset。
            token = _current.set(record)
            try:
                event = await anext(iterator)
            except StopAsyncIteration:
                break
            finally:
                _current.reset(token)
            record["event_count"] += 1
            record["selected_count"] = len(event.selected)
            record["candidate_count"] = len(event.candidates)
            activity = event.activity
            if activity.get("type") == "tool.started":
                name = activity.get("name")
                name = name if name in TOOLS else "other"
                record["tools"][name] = record["tools"].get(name, 0) + 1
            if event.kind in {"complete", "refusal", "error", "ignored"}:
                record["status"] = {"complete": "completed", "error": "failed"}.get(event.kind, event.kind)
                # HTTP 消费者收到终态就结束，先保存再交付终态。
                await save()
            yield event
    except asyncio.CancelledError:
        record["status"] = "cancelled"
        raise
    except Exception:
        record["status"] = "failed"
        raise
    finally:
        await save()
        await iterator.aclose()
