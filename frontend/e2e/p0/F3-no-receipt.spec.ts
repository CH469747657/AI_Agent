/**
 * F3: 无票报销
 * 「无票报销 8月1日 120元 打车费」→ 创建无票发票
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";

test.describe("F3 无票报销", () => {
  test("员工输入「无票报销 8月1日 120元 打车费」", async ({ page }) => {
    test.setTimeout(120_000);
    await loginAsEmployee(page, "EMP001", "123456");
    await page.goto("/portal/home");

    await page.fill('[data-testid="chat-input"]', "无票报销 8月1日 120元 打车费");
    await page.click('[data-testid="chat-send"]');

    // 等待助手响应（含「无票」+「打车费」）
    let text = "";
    const deadline = Date.now() + 110_000;
    while (Date.now() < deadline) {
      const all = page.locator('[data-role="assistant"]');
      const count = await all.count();
      for (let i = count - 1; i >= 0; i--) {
        const t = (await all.nth(i).textContent()) || "";
        if (
          t &&
          (t.includes("无票") || t.includes("无凭证")) &&
          t.includes("打车费") &&
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

    // 断言：含无票/打车费/120
    expect(text).toMatch(/无票|无凭证/);
    expect(text).toContain("打车费");
    expect(text).toContain("120");
    // 助手响应虽不复述日期，但 DB 已记录（已通过单元测试 T1 验证日期写入）
  });
});
