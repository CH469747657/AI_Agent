/**
 * F8: 超管全公司洞察
 * 「8月公司总费用」→ 返回全公司费用统计
 */

import { test, expect } from "../fixtures";
import { loginAsBoss } from "../helpers/auth";

test.describe("F8 超管全公司洞察", () => {
  test("超管输入「8月公司总费用」", async ({ page }) => {
    test.setTimeout(120_000);
    await loginAsBoss(page, "zhang", "zhang");
    await page.goto("/boss/chat");

    const chatInput = page.locator('[data-testid="chat-input"]');
    await expect(chatInput).toBeVisible({ timeout: 10_000 });
    await chatInput.fill("8月公司总费用");
    await page.click('[data-testid="chat-send"]');

    let text = "";
    const deadline = Date.now() + 110_000;
    while (Date.now() < deadline) {
      const all = page.locator('[data-role="assistant"]');
      const count = await all.count();
      for (let i = count - 1; i >= 0; i--) {
        const t = (await all.nth(i).textContent()) || "";
        if (
          t &&
          (t.includes("总费用") || t.includes("合计") || t.includes("总计") || t.includes("公司")) &&
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

    // 断言：含金额/费用相关字样
    expect(text).toMatch(/总费用|合计|总计|费用|报销/);
  });
});
