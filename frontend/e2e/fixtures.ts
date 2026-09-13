/**
 * 全局测试 fixture — 每个测试前清登录态 + 拦截外部字体
 *
 * 用法：
 *   import { test, expect } from "./fixtures";
 *   test("F1", async ({ page }) => { ... });
 */

import { test as base } from "@playwright/test";
import { clearAuth } from "./helpers/auth";

// 扩展 base test，加 beforeEach 自动清登录态 + 拦截 Google Fonts
export const test = base.extend({});

test.beforeEach(async ({ page }) => {
  // 拦截 Google Fonts — 国内访问慢/被墙会阻塞 page load 事件
  await page.route("**/*", (route) => {
    const url = route.request().url();
    if (url.includes("fonts.googleapis.com") || url.includes("fonts.gstatic.com")) {
      route.abort();
    } else {
      route.continue();
    }
  });
  await clearAuth(page);
});

export { expect } from "@playwright/test";
