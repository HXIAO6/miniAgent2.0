"""独立本地安全审计：固定枚举字段、来源摘要和规则编号，不保存问题或原文。"""
from datetime import datetime, timezone
import hashlib
import json
import threading

from miniagent.config import logger, settings
from miniagent.runtime import current_config

_lock = threading.Lock()
_stages = {"ingest", "retrieval", "tool", "output", "workflow"}
_codes = {"secret_exfiltration", "instruction_override", "role_spoofing", "active_html", "tool_escalation",
          "credential_material", "configured_secret", "source_denied", "credential_pattern", "active_content",
          "automatic_image_request", "policy_loaded", "get_current_time", "search_web", "read_local_file",
          "write_local_file", "approval_required"}


def record_decision(stage, outcome, codes=(), source="", config=None):
    """逐日 JSONL；线程内串行写入；写盘失败仅告警，不伪装成审计成功。"""
    config = config or current_config(settings)
    if not config.audit_enabled:
        return False
    if stage not in _stages or outcome not in {"allowed", "blocked"}:
        raise ValueError("安全审计字段无效。")
    now = datetime.now(timezone.utc)
    record = dict(schema_version=1, timestamp=now.isoformat(), stage=stage, outcome=outcome,
                  codes=sorted({code if code in _codes else "other" for code in codes}),
                  source_sha256=hashlib.sha256(source.encode()).hexdigest() if source else None)
    try:
        with _lock:
            config.audit_dir.mkdir(parents=True, exist_ok=True)
            with (config.audit_dir / (now.strftime("%Y-%m-%d") + ".jsonl")).open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except OSError:
        logger.warning("安全审计写入失败；未记录原文或异常详情。")
        return False
