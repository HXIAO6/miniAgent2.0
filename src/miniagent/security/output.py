"""输出门禁：审核完整快照后发布，防止分块密钥在检查前到达客户端。"""
from dataclasses import replace
import asyncio
import re

from miniagent.config import settings
from miniagent.security.policy import audit


def output_findings(text, secrets=()):
    """识别实际配置密钥及常见凭据形式；不将手机号等业务数据一律视为秘密。"""
    codes = []
    if any(secret and len(secret) >= 6 and secret in text for secret in secrets):
        codes.append("configured_secret")
    if re.search(r"\bsk-[A-Za-z0-9_-]{16,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", text):
        codes.append("credential_pattern")
    if re.search(r"<\s*(?:script|iframe|object|embed|img|svg|style)\b|\bonerror\s*=|javascript\s*:", text, re.I):
        codes.append("active_content")
    if re.search(r"!\[[^\]]*\]\s*\(", text) or re.search(r"!\[[^\]]*\]\s*\[", text):
        # Markdown 图片可能自动请求外站，不能等用户点击后再处理。
        codes.append("automatic_image_request")
    return tuple(codes)


async def guarded_events(events, secrets=None):
    """正文和推理都不在终态审核前释放；进度及工具事件仍可实时传递。"""
    secrets = secrets if secrets is not None else (settings.openai_api_key, settings.tavily_api_key)
    async for event in events:
        terminal = event.kind in {"complete", "refusal", "error"}
        if event.kind == "error":
            # 异常消息可能携带 SDK 响应、连接串及路径，对两个界面统一隐藏。
            yield replace(event, answer="运行失败，请检查服务状态后重试。", status="本轮运行失败。")
            continue
        if not terminal:
            activity = event.activity
            status = ("工具执行：" + activity["name"] if activity and activity.get("name") in
                      {"get_current_time", "search_knowledge", "search_web", "read_local_file"}
                      else "正在执行；回答完成后进行安全检查。")
            yield replace(event, answer="", status=status)
            continue
        codes = output_findings(event.answer, secrets)
        audit("output", "blocked" if codes else "allowed", codes)
        if codes:
            yield replace(event, kind="refusal", answer="回答未通过安全检查，已阻止展示。请调整问题后重试。",
                          status="安全检查阻止了敏感或活动内容。")
        else:
            # 只对已审核的正文分段发布，协议保留增量能力，但首字延迟包括完整生成时间。
            if event.kind == "complete":
                for end in range(64, len(event.answer), 64):
                    yield replace(event, kind="progress", persist=False, answer=event.answer[:end],
                                  status="回答已通过基础安全检查。", update_scores=False, activity={})
                    await asyncio.sleep(0)
            # 不展示原始推理；它也可能复述秘密或恶意文档内容。
            yield replace(event, status="回答已通过基础安全检查。")
