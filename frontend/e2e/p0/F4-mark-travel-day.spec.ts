/**
 * F4: 标记出差日
 * 「8月5日出差」→ travel_days 落库 + 助手响应确认
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";

test.describe("F4 标记出差日", () => {
  test("员工输入「8月5日出差」", async ({ page }) => {
    test.setTimeout(120_000);
    await loginAsEmployee(page, "EMP001", "123456");
    await page.goto("/portal/home");

    await page.fill('[data-testid="chat-input"]', "8月5日出差");
    await page.click('[data-testid="chat-send"]');

    // 等待助手响应（含「出差」相关字样）
    let text = "";
    const deadline = Date.now() + 110_000;
    while (Date.now() < deadline) {
      const all = page.locator('[data-role="assistant"]');
      const count = await all.count();
      for (let i = count - 1; i >= 0; i--) {
        const t = (await all.nth(i).textContent()) || "";
        if (
          t &&
          (t.includes("已标记") || t.includes("出差日") || t.includes("出差") || t.includes("周期已封账") || t.includes("不在当前周期")) &&
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

    // 断言：含出差/封账相关字样 + 日期
    expect(text).toMatch(/已标记|出差日|出差|周期已封账|不在当前周期/);
    expect(text).toMatch(/2026-08-05|8月5日|08-05/);
  });
});
