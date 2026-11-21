import { describe, expect, it } from "vitest";
import { consumeEvents } from "./api";
import type { RunEvent } from "./types";

describe("SSE 协议", () => {
  it("跨字节分块仍正确解析中文、替换事件和结束事件", async () => {
    const events: RunEvent[] = [];
    const source = [
      { type: "message.delta", seq: 1, data: { text: "九天\n" } },
      { type: "message.replace", seq: 2, data: { text: "九天[资料1]。" } },
      { type: "run.completed", seq: 3, data: { status: "completed" } },
    ].map((event) => `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`).join("");
    const bytes = new TextEncoder().encode(source);
    const stream = new ReadableStream<Uint8Array>({ start(controller) {
      for (let index = 0; index < bytes.length; index += 2) controller.enqueue(bytes.slice(index, index + 2));
      controller.close();
    } });
    await consumeEvents(new Response(stream), (event) => events.push(event));
    expect(events[0].data.text).toBe("九天\n");
    expect(events[1].type).toBe("message.replace");
    expect(events).toHaveLength(3);
  });

  it("没有结束事件的断流不能视为完成", async () => {
    await expect(consumeEvents(new Response("data: {\"type\":\"message.delta\",\"data\":{\"text\":\"部分\"}}\n\n"), () => {})).rejects.toThrow("连接中断");
  });
});
