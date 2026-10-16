/**
 * 管理员通过 Settings → LLM API 参数 修改 API Key
 *
 * 验证：
 * - 进入 Settings，切到「LLM API 参数」Tab
 * - 填入新 API key → 保存配置按钮变 enabled
 * - 点保存 → 显示「保存成功，配置已热更新到运行时」
 * - 后端 DB 已更新（掩码前 4 后 4 字符变化）
 * - 重新 GET /api/settings/llm 返回新掩码
 * - 用新 key 调对话验证 LLM 可用
 */

import { test, expect } from "../fixtures";
import { loginAsAdmin } from "../helpers/auth";

const NEW_API_KEY = "sk-TEST-PLACEHOLDER-KEY-2";

test.describe("Settings LLM API key 修改", () => {
  test("管理员改 API Key 保存生效", async ({ page, request }) => {
    test.setTimeout(60_000);

    // 1. 先通过 API 把 key 设回旧值，确保测试起点干净
    const adminToken = await request.post("/api/admin/auth/login", {
      data: { username: "admin", password: "123456" },
    });
    const tokenBody = await adminToken.json();
    const headers = { Authorization: `Bearer ${tokenBody.access_token}` };

    // 设回旧 key（避免测试前已被改成新 key）
    await request.put("/api/settings/llm", {
      headers,
      data: { api_key: "sk-TEST-PLACEHOLDER-KEY" },
    });

    // 2. 浏览器登录管理员
    await loginAsAdmin(page, "admin", "123456");
    await page.goto("/settings", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

    // 3. 切到「LLM API 参数」Tab
    await page.click('button:has-text("LLM API 参数")');

    // 4. 等 API Key 输入框加载（默认有掩码值）
    const apiKeyInput = page.locator('input[type="password"], input[type="text"]').filter({ hasText: "" }).first();
    await expect(apiKeyInput).toBeVisible({ timeout: 10_000 });

    // 5. 清空 + 填新 key
    await apiKeyInput.fill("");
    await apiKeyInput.fill(NEW_API_KEY);

    // 6. 等「保存配置」按钮变 enabled（isDirty=true 触发）
    const saveBtn = page.locator('button:has-text("保存配置")').first();
    await expect(saveBtn).toBeEnabled({ timeout: 5_000 });

    // 7. 点保存
    await saveBtn.click();

    // 8. 等待「保存成功」消息出现
    await expect(
      page.locator("text=保存成功").first()
    ).toBeVisible({ timeout: 15_000 });

    // 9. 通过 API 验证 DB 已更新（掩码前 4 后 4 应是新 key）
    const getResp = await request.get("/api/settings/llm", { headers });
    const getBody = await getResp.json();
    expect(getBody.llm_api_key).toBe("sk-TEST...KEY-2");

    // 10. 验证新 key 能调 LLM（通过对话端点测试 agent 是否工作）
    const empLoginResp = await request.post("/api/portal/auth/login", {
      data: { employee_no: "EMP001", password: "123456" },
    });
    const empBody = await empLoginResp.json();
    const empHeaders = { Authorization: `Bearer ${empBody.access_token}` };

    // 先重置对话避免缓存
    await request.post("/api/portal/dialog/reset", {
      headers: empHeaders,
      data: { user_id: "EMP001", role: "employee" },
    });

    const chatResp = await request.post("/api/portal/dialog/message", {
      headers: empHeaders,
      data: { user_id: "EMP001", text: "我的发票", role: "employee" },
      timeout: 60000,
    });
    const chatBody = await chatResp.json();
    // agent 应该回复非空文本，不是 "Agent 未返回有效响应"
    expect(chatBody.text).toBeTruthy();
    expect(chatBody.text).not.toContain("Agent 未返回有效响应");
  });
});
