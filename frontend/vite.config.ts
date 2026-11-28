import pkg from "./package.json" with { type: "json" };
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // v0.8.2 版本号单一事实来源：顶栏显示 v{__APP_VERSION__}，只改 package.json 一处
  define: { __APP_VERSION__: JSON.stringify(pkg.version) },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } }
  }
});
