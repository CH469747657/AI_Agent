/**
 * F5: 查询我的发票
 * 「我的发票」→ 返回发票列表表格
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";

test.describe("F5 查询我的发票", () => {
  test("员工输入「我的发票」", async ({ page }) => {
    test.setTimeout(120_000);
    await loginAsEmployee(page, "EMP001", "123456");
    await page.goto("/portal/home");

    await page.fill('[data-testid="chat-input"]', "我的发票");
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
          t.includes("发票") &&
          (t.includes("张") || t.includes("合计") || t.includes("暂无") || t.includes("上传过")) &&
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

    // 断言：含发票相关字样
    expect(text).toContain("发票");
    // 应有张数或「暂无」字样
    expect(text).toMatch(/张|暂无|合计|上传过/);
  });
});
