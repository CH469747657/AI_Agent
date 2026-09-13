/**
 * 冒烟测试 — 验证 Playwright 环境就绪
 *
 * 不依赖业务功能，仅验证：
 * - dev server 可访问
 * - 登录页正常加载
 * - 员工登录链路通
 */

import { test, expect } from "./fixtures";
import { loginAsEmployee } from "./helpers/auth";

test.describe("冒烟测试 — 环境验证", () => {
  test("dev server 可访问且登录页加载", async ({ page }) => {
    await page.goto("/portal/login");
    await expect(page).toHaveURL(/\/portal\/login/);
    // 登录页有"工号"输入框
    await expect(page.locator('input[placeholder*="工号"]')).toBeVisible();
  });

  test("员工 EMP001 登录成功跳转到 home", async ({ page }) => {
    await loginAsEmployee(page, "EMP001", "123456");
    // 跳转到 home 或其他 portal 页
    await expect(page).toHaveURL(/\/portal\/(home|invoices|reimbursements)/);
    // localStorage 应有 token
    const token = await page.evaluate(() => localStorage.getItem("portal_token"));
    expect(token).toBeTruthy();
  });
});
