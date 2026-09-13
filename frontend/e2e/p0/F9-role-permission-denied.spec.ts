/**
 * F9: 角色越权拦截
 * 员工问「全公司费用」→ 拒绝 + 提示无权限
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";

test.describe("F9 角色越权拦截", () => {
  test("员工问「全公司费用」→ 拒绝", async ({ page }) => {
    test.setTimeout(120_000);
    await loginAsEmployee(page, "EMP001", "123456");
    await page.goto("/portal/home");

    await page.fill('[data-testid="chat-input"]', "全公司费用");
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
          (t.includes("权限") || t.includes("只能看本人") || t.includes("无法") || t.includes("无权")) &&
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

    // 断言：含权限拒绝字样
    expect(text).toMatch(/权限|只能看本人|无法|无权/);
  });
});
