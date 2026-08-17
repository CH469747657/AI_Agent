import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",  // 绑定所有网卡，手机可通过局域网 IP 访问
    port: 13000,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:18080",
        changeOrigin: true,
      },
    },
  },
});
