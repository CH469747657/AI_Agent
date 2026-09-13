/**
 * F10: 删除发票
 * 先上传一张 → 再「删除上一张」→ 列表更新
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const FIXTURE = path.resolve(__dirname, "../fixtures/payment_screenshot.jpg");

test.describe("F10 删除发票", () => {
  test("员工上传后「删除上一张」", async ({ page }) => {
    test.setTimeout(240_000); // 上传 + 删除两轮 LLM 调用
    await loginAsEmployee(page, "EMP001", "123456");
    await page.goto("/portal/home");

    // 1. 上传一张图 + 文本
    await page.setInputFiles('[data-testid="chat-file-input"]', FIXTURE);
    await page.fill('[data-testid="chat-input"]', "项目投标费");
    await page.click('[data-testid="chat-send"]');

    // 等上传完成（助手响应）
    let uploadText = "";
    const deadline1 = Date.now() + 170_000;
    while (Date.now() < deadline1) {
      const all = page.locator('[data-role="assistant"]');
      const count = await all.count();
      for (let i = count - 1; i >= 0; i--) {
        const t = (await all.nth(i).textContent()) || "";
        if (
          t &&
          t.includes("项目投标费") &&
          !t.endsWith("…") &&
          !t.includes("Agent 推理中") &&
          !t.includes("正在")
        ) {
          uploadText = t;
          break;
        }
      }
      if (uploadText) break;
      await page.waitForTimeout(1000);
    }
    expect(uploadText).toContain("项目投标费");

    // 2. 输入「删除上一张」
    await page.fill('[data-testid="chat-input"]', "删除上一张");
    await page.click('[data-testid="chat-send"]');

    // 等删除响应（含「已删除」或「为您删除」字样）
    let deleteText = "";
    const deadline2 = Date.now() + 110_000;
    while (Date.now() < deadline2) {
      const all = page.locator('[data-role="assistant"]');
      const count = await all.count();
      for (let i = count - 1; i >= 0; i--) {
        const t = (await all.nth(i).textContent()) || "";
        if (
          t &&
          (t.includes("已删除") || t.includes("为您删除") || t.includes("已为您删除")) &&
          !t.endsWith("…") &&
          !t.includes("Agent 推理中") &&
          !t.includes("正在")
        ) {
          deleteText = t;
          break;
        }
      }
      if (deleteText) break;
      await page.waitForTimeout(1000);
    }

    expect(deleteText).toMatch(/已删除|为您删除|已为您删除/);
  });
});
