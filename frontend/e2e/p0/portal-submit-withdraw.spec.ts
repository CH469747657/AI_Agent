/**
 * 员工端 Portal 提交/撤回报销单 E2E
 *
 * 验证：
 * - 列表视图 DRAFT 报销单显示「提交」按钮
 * - 详情视图顶部 DRAFT 状态显示「提交报销单」按钮
 * - 点提交 → 状态变 SUBMITTED
 * - SUBMITTED 后显示「撤回」按钮 → 点击撤回 → 状态变回 DRAFT
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";

test.describe("员工 Portal 提交/撤回报销单", () => {
  test.beforeEach(async ({ page, request }) => {
    const loginResp = await request.post("/api/portal/auth/login", {
      data: { employee_no: "EMP001", password: "123456" },
    });
    const body = await loginResp.json();
    const headers = { Authorization: `Bearer ${body.access_token}` };

    await request.post("/api/portal/dialog/reset", {
      headers,
      data: { user_id: "EMP001", role: "employee" },
    });

    // 确保当前周期有 DRAFT 报销单（幂等）
    await request.post("/api/portal/reimbursements/generate", { headers });

    await loginAsEmployee(page, "EMP001", "123456");
  });

  test("列表视图 DRAFT 显示提交按钮 + 详情顶部显示提交按钮", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/portal/reimbursements", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

    // 列表 DRAFT 报销单应有「提交」按钮
    const listSubmitBtn = page.locator('button:has-text("提交")').first();
    await expect(listSubmitBtn).toBeVisible({ timeout: 15_000 });

    // 点进详情
    await page.locator('text=报销单 #').first().click();
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    // 详情顶部应有「提交报销单」按钮
    const detailSubmitBtn = page.locator('button:has-text("提交报销单")').first();
    await expect(detailSubmitBtn).toBeVisible({ timeout: 15_000 });
  });

  test("提交 → 状态变 SUBMITTED → 撤回 → 状态变回 DRAFT", async ({ page }) => {
    test.setTimeout(90_000);
    await page.goto("/portal/reimbursements", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

    // 1. 点列表的「提交」按钮
    const listSubmitBtn = page.locator('button:has-text("提交")').first();
    await expect(listSubmitBtn).toBeVisible({ timeout: 15_000 });
    await listSubmitBtn.click();

    // 2. 等状态变 SUBMITTED — 出现「撤回」按钮
    const withdrawBtn = page.locator('button:has-text("撤回")').first();
    await expect(withdrawBtn).toBeVisible({ timeout: 15_000 });

    // 3. 点「撤回」按钮 — 浏览器 confirm 弹窗接受
    page.on("dialog", (d) => d.accept());
    await withdrawBtn.click();

    // 4. 等状态变回 DRAFT — 重新出现「提交」按钮
    await expect(listSubmitBtn).toBeVisible({ timeout: 15_000 });
  });
});
