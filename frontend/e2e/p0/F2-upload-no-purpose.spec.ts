/**
 * F2: 上传后无用途追问
 * 仅上传图无文本 → 助手追问用途 + quick_replies 气泡
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FIXTURE = path.resolve(__dirname, "../fixtures/payment_screenshot.jpg");

test.describe("F2 上传后无用途追问", () => {
  test("仅上传图片无文本 → 助手追问用途", async ({ page }) => {
    test.setTimeout(180_000);
    await loginAsEmployee(page, "EMP001", "123456");
    await page.goto("/portal/home");

    await page.setInputFiles('[data-testid="chat-file-input"]', FIXTURE);
    await expect(page.locator('[data-testid="chat-send"]')).toBeEnabled({ timeout: 5_000 });
    await page.click('[data-testid="chat-send"]');

    // 等待助手最终响应（追问用途）
    let text = "";
    const deadline = Date.now() + 170_000;
    while (Date.now() < deadline) {
      const all = page.locator('[data-role="assistant"]');
      const count = await all.count();
      for (let i = count - 1; i >= 0; i--) {
        const t = (await all.nth(i).textContent()) || "";
        // 追问用途的响应含「用途」且非进度文案
        if (
          t &&
          t.includes("用途") &&
          !t.endsWith("…") &&
          !t.includes("Agent 推理中") &&
          !t.includes("正在识别") &&
          !t.includes("正在提取")
        ) {
          text = t;
          break;
        }
      }
      if (text) break;
      await page.waitForTimeout(1000);
    }

    expect(text).toContain("用途");

    // 验证 quick_replies 气泡出现（data-quick-reply 属性）
    const quickReplies = page.locator('[data-quick-reply]');
    await expect(quickReplies.first()).toBeVisible({ timeout: 5_000 });
    const count = await quickReplies.count();
    expect(count).toBeGreaterThanOrEqual(1);
  });
});
