import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:8010",
    headless: true,
    // 使用已安装的 Edge，不额外下载浏览器或把模型/缓存放进系统目录。
    channel: "msedge",
    screenshot: "only-on-failure",
  },
});
