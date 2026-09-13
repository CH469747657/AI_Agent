/**
 * F6: 查询我的报销单
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";

test.describe("F6 查询我的报销单", () => {
  test("员工输入「我的报销单」", async ({ page }) => {
    test.setTimeout(120_000);
    await loginAsEmployee(page, "EMP001", "123456");
    await page.goto("/portal/home");

    await page.fill('[data-testid="chat-input"]', "我的报销单");
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
          t.includes("报销单") &&
          (t.includes("条") || t.includes("暂无") || t.includes("记录") || t.includes("信息") || t.includes("笔")) &&
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

    expect(text).toContain("报销单");
    expect(text).toMatch(/条|暂无|记录|信息|笔/);
  });
});
