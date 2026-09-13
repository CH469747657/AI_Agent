/**
 * F1: 员工上传支付截图 + "项目投标费 8月2日"
 * 验证：用户气泡有图、助手气泡无图、类型/用途/日期正确
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FIXTURE = path.resolve(__dirname, "../fixtures/payment_screenshot.jpg");

test.describe("F1 上传发票 + 用途+日期拆分", () => {
  test("员工上传支付截图+「项目投标费 8月2日」", async ({ page }) => {
    test.setTimeout(180_000); // LLM 调用慢，180s
    await loginAsEmployee(page, "EMP001", "123456");
    await page.goto("/portal/home");

    // 上传 + 填文本 + 发送
    await page.setInputFiles('[data-testid="chat-file-input"]', FIXTURE);
    await page.fill('[data-testid="chat-input"]', "项目投标费 8月2日");
    await expect(page.locator('[data-testid="chat-send"]')).toBeEnabled({ timeout: 5_000 });
    await page.click('[data-testid="chat-send"]');

    // 等助手新响应出现（排除欢迎气泡）
    // 策略：等 user 消息出现 → 等新的 assistant 消息文本非欢迎
    await expect(page.locator('[data-role="user"]').first()).toContainText("项目投标费", { timeout: 10_000 });

    // 持续轮询，等助手最终响应（含「项目投标费」字样的助手消息）
    // 进度文案不含最终用户内容，故以最终文案为准
    let text = "";
    const deadline = Date.now() + 170_000;
    while (Date.now() < deadline) {
      const all = page.locator('[data-role="assistant"]');
      const count = await all.count();
      for (let i = count - 1; i >= 0; i--) {
        const t = (await all.nth(i).textContent()) || "";
        // 真正的响应应包含「项目投标费」（LLM 复述用户用途）且不是进度文案
        // 进度文案特征：含「…」或「推理中」/「正在识别」等
        if (
          t &&
          t.includes("项目投标费") &&
          !t.endsWith("…") &&
          !t.includes("Agent 推理中") &&
          !t.includes("正在识别") &&
          !t.includes("正在提取") &&
          !t.includes("正在查重")
        ) {
          text = t;
          break;
        }
      }
      if (text) break;
      await page.waitForTimeout(1000);
    }

    // 用户气泡：有 1 个 img + 含文本
    await expect(page.locator('[data-role="user"] img')).toHaveCount(1);
    // 助手气泡：无 img
    await expect(page.locator('[data-role="assistant"] img')).toHaveCount(0);

    expect(text).toContain("支付截图");
    expect(text).toContain("项目投标费");
    expect(text).toMatch(/2026-08-02/);
  });
});
