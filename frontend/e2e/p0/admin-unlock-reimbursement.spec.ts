/**
 * 管理员手动 unlock + 重新封账 E2E
 *
 * 覆盖：
 * - 管理员报销单详情页可见「解锁报销单」按钮（封账时）
 * - 点「解锁报销单」→ 弹窗填原因 → 提交 → 详情页显示审计信息
 * - unlock 后「重新封账」按钮出现 → 点击 → 审计信息清空
 *
 * 前置条件：存在一份已封账报销单。本 spec 不构造测试数据，依赖现有 DB；
 * 若无封账报销单，test.skip 而非失败。
 */

import { test, expect } from "../fixtures";
import { loginAsAdmin } from "../helpers/auth";

test.describe("管理员手动 unlock 报销单", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page, "admin", "123456");
  });

  test("unlock + 重新封账闭环", async ({ page }) => {
    test.setTimeout(60_000);

    // 1. 进入报销单列表
    await page.goto("/reimbursements", { waitUntil: "domcontentloaded" });

    // 2. 找一份已封账报销单（is_cycle_locked=true 列里通常有 🔒 标记）
    //    若无封账报销单，跳过
    const lockedRow = page.locator("tr", { has: page.locator("text=🔒") }).first();
    const hasLocked = await lockedRow.isVisible().catch(() => false);
    if (!hasLocked) {
      test.skip(true, "当前 DB 无已封账报销单，跳过 unlock E2E");
      return;
    }

    // 3. 点该行进入详情
    await lockedRow.locator("a, button").first().click();

    // 4. 详情页应出现「解锁报销单」按钮（红色）
    const unlockBtn = page.locator('button:has-text("解锁报销单")').first();
    await expect(unlockBtn).toBeVisible({ timeout: 15_000 });

    // 5. 点击 → 弹出对话框
    await unlockBtn.click();
    const dialog = page.locator('[role="dialog"], .fixed.inset-0').first();
    await expect(dialog).toBeVisible({ timeout: 5_000 });

    // 6. 填写原因
    const reason = "E2E 测试解锁 — 发票需补充";
    await dialog.locator("textarea").fill(reason);

    // 7. 提交（点对话框内的「解锁」按钮，避开外层同名按钮）
    await dialog.locator('button:has-text("解锁")').click();

    // 8. 等待详情页刷新 — 出现审计信息「已解锁 by ...」
    await expect(
      page.locator("text=已解锁").first()
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.locator(`text=${reason}`).first()).toBeVisible();

    // 9. 此时「重新封账」按钮应可见（绿色）
    const lockBtn = page.locator('button:has-text("重新封账")').first();
    await expect(lockBtn).toBeVisible({ timeout: 5_000 });

    // 10. 点「重新封账」→ 浏览器 confirm 弹窗 → 接受
    page.on("dialog", (d) => d.accept());
    await lockBtn.click();

    // 11. 等待刷新 — 审计信息消失，回到 🔒 已封账状态
    await expect(
      page.locator("text=已解锁").first()
    ).toBeHidden({ timeout: 15_000 });
  });
});
