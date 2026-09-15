/**
 * 员工端 Portal 删除报销单按钮 E2E
 *
 * 验证：
 * - 列表视图 DRAFT 报销单显示「删除」按钮
 * - 点删除 → 弹出确认弹窗 → 取消（不实际删，避免破坏 DB）
 * - 详情视图顶部 DRAFT 状态显示「删除」按钮
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";

test.describe("员工 Portal 删除报销单按钮", () => {
  test.beforeEach(async ({ page, request }) => {
    // 登录拿 token
    const loginResp = await request.post("/api/portal/auth/login", {
      data: { employee_no: "EMP001", password: "123456" },
    });
    const body = await loginResp.json();
    const headers = { Authorization: `Bearer ${body.access_token}` };

    // 重置对话缓存
    await request.post("/api/portal/dialog/reset", {
      headers,
      data: { user_id: "EMP001", role: "employee" },
    });

    // 确保当前周期有一份 DRAFT 报销单（幂等，已存在则返回现有）
    await request.post("/api/portal/reimbursements/generate", { headers });

    // 浏览器登录
    await loginAsEmployee(page, "EMP001", "123456");
  });

  test("列表视图 DRAFT 报销单显示删除按钮", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/portal/reimbursements", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

    // 至少有一个「删除」按钮（DRAFT 报销单才显示）
    const deleteBtn = page.locator('button:has-text("删除")').first();
    await expect(deleteBtn).toBeVisible({ timeout: 15_000 });
  });

  test("点删除按钮弹出确认弹窗 → 取消不实际删除", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/portal/reimbursements", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

    // 记录删除前报销单数量
    const beforeCount = await page.locator('text=报销单 #').count();

    // 点第一个删除按钮
    const deleteBtn = page.locator('button:has-text("删除")').first();
    await deleteBtn.click();

    // 应弹出确认弹窗（实际文案：「确定要删除以下报销单吗？」+「确认删除」按钮）
    const modal = page.locator("text=确定要删除以下报销单").first();
    await expect(modal).toBeVisible({ timeout: 5_000 });

    // 点「取消」（避免实际删除 DB 数据）
    await page.locator('button:has-text("取消")').first().click();

    // 弹窗应消失
    await expect(modal).toBeHidden({ timeout: 5_000 });

    // 报销单数量应不变
    const afterCount = await page.locator('text=报销单 #').count();
    expect(afterCount).toBe(beforeCount);
  });

  test("详情视图顶部 DRAFT 显示删除按钮", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/portal/reimbursements", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

    // 点进第一个报销单详情
    const firstRow = page.locator('text=报销单 #').first();
    await firstRow.click();
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    // 详情顶部应有删除按钮（红色边框）
    const deleteBtn = page.locator('button:has-text("删除")').first();
    await expect(deleteBtn).toBeVisible({ timeout: 15_000 });
  });
});
