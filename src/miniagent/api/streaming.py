"""SSE 编码只负责传输格式，不操作模型或会话。"""
import json


async def encode_events(events):
    """每条 JSON 独占 data 行，换行由编码器转义。"""
    async for event in events:
        if event is None:
            yield ": keepalive\n\n"
        else:
            yield f"id: {event['seq']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
