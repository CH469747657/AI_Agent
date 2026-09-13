/**
 * F7: 管理员审批通过
 * 「批准陈辉的报销单」→ 触发审批流程
 */

import { test, expect } from "../fixtures";
import { loginAsAdmin } from "../helpers/auth";
import { openChatIfCollapsed } from "../helpers/chat";

test.describe("F7 管理员审批通过", () => {
  test("管理员输入「待审报销单」", async ({ page }) => {
    test.setTimeout(120_000);
    await loginAsAdmin(page, "admin", "123456");
    await page.goto("/admin");

    // 浮窗折叠则点开
    await openChatIfCollapsed(page);
    const chatInput = page.locator('[data-testid="chat-input"]');
    await expect(chatInput).toBeVisible({ timeout: 10_000 });

    await chatInput.fill("待审报销单");
    await page.click('[data-testid="chat-send"]');

    // 等待助手响应
    let text = "";
    const deadline = Date.now() + 110_000;
    while (Date.now() < deadline) {
      const all = page.locator('[data-role="assistant"]');
      const count = await all.count();
      for (let i = count - 1; i >= 0; i--) {
        const t = (await all.nth(i).textContent()) || "";
        if (
          t &&
          (t.includes("待审") || t.includes("审批") || t.includes("没有待审批")) &&
          !t.endsWith("…") &&
          !t.includes("Agent 推理中") &&
          !t.includes("正在")
        ) {
          text = t;
          break;
        }
      }
      if (text) break;
      await page.waitForTimeout(1000);
    }

    // 断言：含待审/审批相关字样
    expect(text).toMatch(/待审|审批|没有待审批/);
  });
});
