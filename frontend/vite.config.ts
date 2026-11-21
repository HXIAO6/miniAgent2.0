import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 浏览器始终请求同源 /api；开发代理和生产 FastAPI 静态服务使用同一套地址。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
