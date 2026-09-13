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

  test("unlock + 重新封账闭环", async ({ page, request }) => {
    test.setTimeout(120_000);

    // 用 API 直接构造测试前置条件：拿任意一份报销单 → 确保它处于锁状态
    const adminToken = await request.post("/api/admin/auth/login", {
      data: { username: "admin", password: "123456" },
    });
    const tokenBody = await adminToken.json();
    const headers = { Authorization: `Bearer ${tokenBody.access_token}` };

    const listResp = await request.get("/api/reimbursements", { headers });
    const listBody = await listResp.json();
    const items = Array.isArray(listBody) ? listBody : (listBody.items ?? listBody.data ?? []);
    if (items.length === 0) {
      test.skip(true, "当前 DB 无报销单，跳过 unlock E2E");
      return;
    }
    const reimb = items[0];
    const reimbId = reimb.id;

    // 确保测试初始状态：报销单是锁的
    if (!reimb.is_cycle_locked) {
      await request.post(`/api/reimbursements/${reimbId}/lock`, { headers });
    } else {
      // 已经锁但可能已经 unlock 过 — 先 re-lock 清空审计字段
      await request.post(`/api/reimbursements/${reimbId}/unlock`, { headers, data: { reason: "E2E 重置" } });
      await request.post(`/api/reimbursements/${reimbId}/lock`, { headers });
    }

    // 1. 进入报销单详情页（用 ?detail=N 查询参数，不是 /N 路由）
    await page.goto(`/reimbursements?detail=${reimbId}`, { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

    // 2. 详情页应出现「解锁报销单」按钮（红色）
    const unlockBtn = page.locator('button:has-text("解锁报销单")').first();
    await expect(unlockBtn).toBeVisible({ timeout: 30_000 });

    // 3. 点击 → 弹出对话框
    await unlockBtn.click();
    const dialog = page.locator('[role="dialog"], .fixed.inset-0').first();
    await expect(dialog).toBeVisible({ timeout: 10_000 });

    // 4. 填写原因
    const reason = "E2E 测试解锁 — 发票需补充";
    await dialog.locator("textarea").fill(reason);

    // 5. 提交（对话框内的「确认解锁」按钮，避开外层同名按钮）
    await dialog.locator('button:has-text("确认解锁")').click();

    // 6. 等待详情页刷新 — 出现审计信息「已解锁 by ...」
    await expect(
      page.locator("text=已解锁").first()
    ).toBeVisible({ timeout: 30_000 });
    await expect(page.locator(`text=${reason}`).first()).toBeVisible();
    await expect(page.locator("text=admin").first()).toBeVisible();

    // 7. 此时「重新封账」按钮应可见（绿色）
    const lockBtn = page.locator('button:has-text("重新封账")').first();
    await expect(lockBtn).toBeVisible({ timeout: 10_000 });

    // 8. 点「重新封账」→ 浏览器 confirm 弹窗 → 接受
    page.on("dialog", (d) => d.accept());
    await lockBtn.click();

    // 9. 等待刷新 — 审计信息消失
    await expect(
      page.locator("text=已解锁").first()
    ).toBeHidden({ timeout: 30_000 });

    // 10. 「解锁报销单」按钮应再次出现
    await expect(
      page.locator('button:has-text("解锁报销单")').first()
    ).toBeVisible({ timeout: 10_000 });
  });
});
