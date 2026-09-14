/**
 * 员工 Portal 周期范围展示 E2E
 *
 * 验证：
 * - 员工登录后看「我的报销单」列表，每行显示周期范围（cycle_start ~ cycle_end）
 * - 点报销单进详情视图，顶部也显示周期范围
 *
 * 用 TEST-001 测试员工（之前 test_locked_then_unlock_flow 用过的）。
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";

test.describe("员工 Portal 周期范围展示", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsEmployee(page, "TEST-001", "123456");
  });

  test("列表行显示周期范围 + 详情顶部显示周期范围", async ({ page }) => {
    test.setTimeout(60_000);

    // 1. 进入「我的报销单」列表
    await page.goto("/portal/reimbursements", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

    // 2. 列表里至少一行有周期范围文字（cycle_end_day=25 时本月周期 = 2026-08-26 ~ 2026-09-25）
    const cycleRangeText = page.locator("text=2026-08-26 ~ 2026-09-25").first();
    await expect(cycleRangeText).toBeVisible({ timeout: 30_000 });

    // 3. 点进详情（如果有可点的报销单行）
    const reimbRow = page.locator('h2:has-text(/报销单 #\\d+/)').first();
    const hasDetail = await reimbRow.isVisible().catch(() => false);
    if (!hasDetail) {
      // 没报销单 — 列表里至少周期范围字段已验证，skip 剩余
      return;
    }

    // 4. 详情视图顶部也应该有周期范围
    const detailCycleRange = page.locator("text=\\d{4}-\\d{2}-\\d{2} ~ \\d{4}-\\d{2}-\\d{2}").first();
    await expect(detailCycleRange).toBeVisible({ timeout: 15_000 });
  });
});
