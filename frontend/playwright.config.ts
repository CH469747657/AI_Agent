import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright 配置
 * - baseURL: 前端 dev server（vite 默认 13000）
 * - 超时：30s/测试，60s/操作（LLM 调用慢，留足余量）
 * - 失败重试：2 次
 * - 报告：HTML + 失败截图 + trace
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false, // 智能问数涉及 LLM 调用，串行避免限流
  forbidOnly: !!process.env.CI,
  retries: 2,
  workers: 1, // 单 worker 串行
  timeout: 120_000, // 单测试 120s（含 LLM 调用 + vite 编译）
  reporter: [
    ["html", { outputFolder: "e2e-report" }],
    ["list"],
  ],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://127.0.0.1:13000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 30_000,
    navigationTimeout: 60_000,
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // 用系统 Chrome 跳过 playwright 下载（CI 之外的环境也常装 Chrome）
        channel: "chrome",
      },
    },
  ],
  // 自动启动 dev server（如果未运行）
  webServer: process.env.E2E_NO_DEV_SERVER
    ? undefined
    : {
        command: "npm run dev",
        url: "http://127.0.0.1:13000",
        reuseExistingServer: true,
        timeout: 60_000,
      },
});
