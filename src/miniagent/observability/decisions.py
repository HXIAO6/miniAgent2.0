"""安全决策统一出口，独立保存审计并累计当前运行统计。"""
import hashlib
from miniagent.config import logger


def audit(stage, outcome, codes=(), source=""):
    """审计只保存阶段、决策、规则和来源摘要，不记录用户问题或原文。"""
    from miniagent.observability.tracing import security_decision
    from miniagent.observability.audit import record_decision
    security_decision(stage, outcome)
    record_decision(stage, outcome, codes, source)
    logger.info("security stage=%s outcome=%s codes=%s source_hash=%s", stage, outcome,
                ",".join(codes) or "none", hashlib.sha256(source.encode()).hexdigest()[:16] if source else "none")

