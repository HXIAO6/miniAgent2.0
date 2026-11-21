"""确定性的安全基础策略：规则可解释，但不声称能够识别所有注入或事实投毒。"""
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from miniagent.config import logger, settings


class SecurityViolation(ValueError):
    """只携带规则编号，不包含原文、密钥或内部路径。"""


def inspect_text(text):
    """归一化后检查高风险指令组合；正常讨论安全概念不因单个关键词被拒绝。"""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    normalized = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", normalized)
    rules = {
        "secret_exfiltration": r"(?:读取|输出|泄露|发送|上传|打印|read|reveal|print|send|exfiltrate).{0,100}(?:\.env|api[_ -]?key|密钥|密码|access[_ -]?token)",
        "instruction_override": r"(?:^|[。！？\n;])\s*(?:请|必须)?\s*(?:(?:忽略|无视|覆盖).{0,20}(?:之前|先前|系统|用户|所有).{0,15}(?:指令|提示|问题)|(?:ignore|disregard).{0,30}(?:previous|system|user|all).{0,20}(?:instructions?|prompts?))",
        "role_spoofing": r"<\|(?:im_start|start_header_id)\|>\s*system|\[\s*system\s*\]|你现在是系统管理员",
        "active_html": r"<\s*(?:script|iframe)\b|\bonerror\s*=|javascript\s*:",
        "tool_escalation": r"(?:执行|运行|调用).{0,40}(?:write_local_file|powershell|cmd\.exe|rm\s+-rf|curl\s+.{0,40}\|)",
        "credential_material": r"\bsk-[a-z0-9_-]{16,}|-----begin (?:rsa |ec |openssh )?private key-----",
    }
    codes = tuple(code for code, pattern in rules.items() if re.search(pattern, normalized, re.S))
    if any(secret and len(secret) >= 6 and secret in text for secret in (settings.openai_api_key, settings.tavily_api_key)):
        codes += ("configured_secret",)
    return codes


def audit(stage, outcome, codes=(), source=""):
    """审计只保存阶段、决策、规则和来源摘要，不记录用户问题或原文。"""
    logger.info("security stage=%s outcome=%s codes=%s source_hash=%s", stage, outcome,
                ",".join(codes) or "none", hashlib.sha256(source.encode()).hexdigest()[:16] if source else "none")


@dataclass(frozen=True)
class SecurityPolicy:
    """单机服务级白/黑名单；不是用户身份体系，模型和浏览器不能覆盖策略。"""

    allowed_sources: tuple[str, ...] | None = None
    denied_sources: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ("get_current_time",)
    scan_documents: bool = True

    def permits_source(self, source):
        return (isinstance(source, str) and bool(source) and source not in self.denied_sources
                and (self.allowed_sources is None or source in self.allowed_sources))

    def require_document(self, source, text):
        """写入向量或替换原件前检查整份文本，拒绝时保留原库和原文件。"""
        codes = inspect_text(source + "\n" + text) if self.scan_documents else ()
        if not self.permits_source(source):
            codes += ("source_denied",)
        audit("ingest", "blocked" if codes else "allowed", codes, source)
        if codes:
            raise SecurityViolation("资料未通过安全检查：" + ", ".join(codes))

    def filter_hits(self, hits):
        """返回副本，拒绝项不进入模型、重排和来源/候选面板。"""
        accepted = []
        for hit in hits:
            source = hit.get("source", "")
            codes = () if self.permits_source(source) else ("source_denied",)
            if self.scan_documents:
                codes += inspect_text("\n".join(str(hit.get(key, "")) for key in ("source", "location", "text")))
            if codes:
                audit("retrieval", "blocked", codes, source)
            else:
                accepted.append(dict(hit))
        return accepted

    def permits_tool(self, name):
        # 未实现人工审批前，高风险写入始终拒绝，配置白名单也不能放开。
        return name != "write_local_file" and name in self.allowed_tools


@lru_cache(maxsize=8)
def load_policy(path):
    """启动时加载本地策略；未知字段或配置错误失败关闭，修改后需重启。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(data) - {"allowed_sources", "denied_sources", "allowed_tools"}:
        raise ValueError("安全策略存在未知字段。")
    for key, value in data.items():
        if key == "allowed_sources" and value is None:
            continue
        if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
            raise ValueError("安全策略名单必须是非空字符串列表。")
    tools = data.get("allowed_tools", ["get_current_time"])
    if set(tools) - {"get_current_time", "search_web", "read_local_file"}:
        raise ValueError("安全策略包含不支持或未获审批的工具。")
    return SecurityPolicy(None if data.get("allowed_sources") is None else tuple(data["allowed_sources"]),
                          tuple(data.get("denied_sources", [])), tuple(tools))


def get_policy():
    return load_policy(str(settings.security_policy_path))
