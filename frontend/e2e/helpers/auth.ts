/**
 * 鉴权 helper：3 种角色自动登录
 *
 * 用法：
 *   import { loginAsEmployee, loginAsAdmin, loginAsBoss } from "./helpers/auth";
 *
 *   test("F1", async ({ page }) => {
 *     await loginAsEmployee(page, "EMP001", "123456");
 *     await page.goto("/portal/home");
 *     // ...
 *   });
 */

import { Page, expect } from "@playwright/test";

/** 带 retry 的 goto — vite dev server 偶发慢时重试 */
export async function gotoWithRetry(page: Page, url: string, retries = 2): Promise<void> {
  for (let i = 0; i <= retries; i++) {
    try {
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30_000 });
      return;
    } catch (e) {
      if (i === retries) throw e;
      await page.waitForTimeout(1000);
    }
  }
}

/** 员工端登录 */
export async function loginAsEmployee(
  page: Page,
  employeeNo = "EMP001",
  password = "123456"
): Promise<void> {
  await gotoWithRetry(page, "/portal/login");
  await page.fill('input[placeholder*="工号"]', employeeNo);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  // 等待跳转到 home 或 invoices
  await page.waitForURL(/\/portal\/(home|invoices|reimbursements)/, { timeout: 15_000, waitUntil: "domcontentloaded" });
}

/** 管理员登录 */
export async function loginAsAdmin(
  page: Page,
  username = "admin",
  password = "123456"
): Promise<void> {
  await gotoWithRetry(page, "/admin/login");
  // 用 id 选择器更稳健（placeholder 是 "admin" 字面值，不是"用户名"提示）
  await page.fill('#login-username', username);
  await page.fill('#login-password', password);
  await page.click('button[type="submit"]');
  // admin 登录后默认跳到 /（管理后台根路径）
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 15_000, waitUntil: "domcontentloaded" });
}

/** 超级管理员（老板端）登录 */
export async function loginAsBoss(
  page: Page,
  username = "zhang",
  password = "zhang"
): Promise<void> {
  await gotoWithRetry(page, "/boss/login");
  await page.fill('input[placeholder*="账号"]', username);
  await page.fill('input[type="password"]', password);
  await page.click('button[type="submit"]');
  // 等待跳转到非 login 页面
  await page.waitForURL((url) => !url.pathname.endsWith("/login"), { timeout: 15_000, waitUntil: "domcontentloaded" });
}

/** 清除登录态（每个测试前调用，避免 localStorage 污染） */
export async function clearAuth(page: Page): Promise<void> {
  await page.context().clearCookies();
  // 不用 addInitScript — 它会在每次导航都执行，包括登录成功后，
  // 把刚设置的 token 又清掉。Playwright 每个测试默认是新 context，localStorage 本来就不共享。
  // 也不 goto 任何路由 — vite dev server 编译慢会超时。
}
