/**
 * E2E 共享 helper — 智能问数对话框交互
 */

import { Page, expect } from "@playwright/test";

/** 如果 ChatWidget 浮窗折叠，点开它 */
export async function openChatIfCollapsed(page: Page): Promise<void> {
  // 浮窗折叠时 toggle 可见；展开后 toggle 不存在
  // 等几秒让 motion 动画完成
  await page.waitForTimeout(500);
  const toggleCount = await page.locator('[data-testid="chat-toggle"]').count();
  if (toggleCount > 0) {
    await page.locator('[data-testid="chat-toggle"]').click();
    await expect(page.locator('[data-testid="chat-input"]')).toBeVisible({ timeout: 10_000 });
  }
}

/** 轮询等待助手最终响应（排除欢迎气泡+思考/进度文案）
 *  matchFn: 判断是否为最终响应的回调
 *  timeout: 默认 110s
 */
export async function waitForAssistantFinalReply(
  page: Page,
  matchFn: (text: string) => boolean,
  timeout = 110_000
): Promise<string> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const all = page.locator('[data-role="assistant"]');
    const count = await all.count();
    for (let i = count - 1; i >= 0; i--) {
      const t = (await all.nth(i).textContent()) || "";
      // 排除欢迎气泡 / 思考气泡 / 进度文案 / 系统错误
      if (
        t &&
        matchFn(t) &&
        !t.endsWith("…") &&
        !t.includes("Agent 推理中") &&
        !t.includes("正在识别") &&
        !t.includes("正在提取") &&
        !t.includes("正在查重") &&
        !t.includes("正在理解") &&
        !t.includes("正在查询") &&
        !t.includes("正在在线验真") &&
        !t.includes("你好陈辉") &&
        !t.includes("我是 AI 报销助手")
      ) {
        return t;
      }
    }
    await page.waitForTimeout(1000);
  }
  return "";
}

/** 等待助手真正回复（"正在思考…"被替换 + 发送按钮重新可用） */
export async function waitForAssistantReply(
  page: Page,
  timeout = 120_000
): Promise<void> {
  // 等发送按钮重新可用（isTyping 结束 = 流式响应完成）
  await expect(page.locator('[data-testid="chat-send"]')).toBeEnabled({
    timeout,
  });
  // 再额外等 500ms 让 React 完成渲染
  await page.waitForTimeout(500);
}

/** 发送文本消息 */
export async function sendText(page: Page, text: string): Promise<void> {
  await page.fill('[data-testid="chat-input"]', text);
  await page.click('[data-testid="chat-send"]');
}

/** 上传文件 + 发送文本 */
export async function uploadFileAndSend(
  page: Page,
  filePath: string,
  text: string
): Promise<void> {
  await page.setInputFiles('[data-testid="chat-file-input"]', filePath);
  await page.fill('[data-testid="chat-input"]', text);
  await page.click('[data-testid="chat-send"]');
}

/** 仅上传文件（无文本） */
export async function uploadFileOnly(page: Page, filePath: string): Promise<void> {
  await page.setInputFiles('[data-testid="chat-file-input"]', filePath);
  await page.click('[data-testid="chat-send"]');
}

/**
 * 取助手最后一条消息文本（排除欢迎气泡）
 * 欢迎气泡含「你好」「我是 AI 报销助手」字样
 */
export async function getLastAssistantText(page: Page): Promise<string> {
  // 助手气泡列表
  const all = page.locator('[data-role="assistant"]');
  const count = await all.count();
  if (count === 0) return "";
  // 从后往前找，跳过欢迎气泡
  for (let i = count - 1; i >= 0; i--) {
    const text = (await all.nth(i).textContent()) || "";
    if (!text.includes("你好") && !text.includes("我是 AI 报销助手")) {
      return text;
    }
  }
  return (await all.last().textContent()) || "";
}
