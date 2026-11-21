"""文本规则检测，支持显式假密钥或请求环境中的真实配置密钥。"""
import re
import unicodedata
from miniagent.runtime import current_config


def inspect_text(text, secrets=None):
    """归一化后检查高风险指令组合；正常讨论安全概念不因单个关键词被拒绝。"""
    config = current_config()
    secrets = secrets if secrets is not None else (config.openai_api_key, config.tavily_api_key, config.langsmith_api_key)
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
    if any(secret and len(secret) >= 6 and secret in text for secret in secrets):
        codes += ("configured_secret",)
    return codes

