"""确定性的安全基础策略：规则可解释，但不声称能够识别所有注入或事实投毒。"""
from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

from miniagent.runtime import current_config, current_policy
from miniagent.security.injection import inspect_text
from miniagent.security.admission import SecurityViolation, require_document
from miniagent.security.context import filter_hits
from miniagent.observability.decisions import audit


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
        """保留原公开接口，委托独立的入库检查实现。"""
        return require_document(self, source, text)

    def filter_hits(self, hits):
        """保留原公开接口，委托独立的上下文过滤实现。"""
        return filter_hits(self, hits)

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
    policy = current_policy()
    return policy if policy is not None else load_policy(str(current_config().security_policy_path))
