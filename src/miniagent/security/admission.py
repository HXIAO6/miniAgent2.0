"""入库安全边界：不操作向量库，失败时仅返回规则编号。"""
from miniagent.security.injection import inspect_text
from miniagent.observability.decisions import audit


class SecurityViolation(ValueError):
    """对外异常不携带原文或密钥。"""


def require_document(policy, source, text):
    """整篇检查先于 embedding 和原文件替换。"""
    codes = inspect_text(source + "\n" + text) if policy.scan_documents else ()
    if not policy.permits_source(source):
        codes += ("source_denied",)
    audit("ingest", "blocked" if codes else "allowed", codes, source)
    if codes:
        raise SecurityViolation("资料未通过安全检查：" + ", ".join(codes))
