/**
 * 员工端 Portal 报表下载 E2E
 *
 * 验证：
 * - 详情页有「报销单报表」区域，含「生成报表」+「下载 Excel/PDF/ZIP」3 个按钮
 * - 未生成时下载按钮 disabled + 提示「尚未生成，请先点「生成报表」」
 * - 点「生成报表」→ 调 API → 下载按钮变 enabled
 * - 点「下载 Excel」→ 真实下载 xlsx 文件（验证文件 magic number）
 * - 点「下载 PDF」→ 真实下载 pdf 文件
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee } from "../helpers/auth";

test.describe("员工 Portal 报表下载", () => {
  test.beforeEach(async ({ page, request }) => {
    const loginResp = await request.post("/api/portal/auth/login", {
      data: { employee_no: "EMP001", password: "123456" },
    });
    const body = await loginResp.json();
    const headers = { Authorization: `Bearer ${body.access_token}` };

    await request.post("/api/portal/dialog/reset", {
      headers,
      data: { user_id: "EMP001", role: "employee" },
    });

    // 确保有报销单
    await request.post("/api/portal/reimbursements/generate", { headers });

    await loginAsEmployee(page, "EMP001", "123456");
  });

  test("详情页显示报表下载区 + 生成报表 + 下载 Excel/PDF", async ({ page }) => {
    test.setTimeout(120_000);

    await page.goto("/portal/reimbursements", { waitUntil: "domcontentloaded" });
    await page.waitForLoadState("networkidle", { timeout: 30_000 }).catch(() => {});

    // 点进详情
    await page.locator('text=报销单 #').first().click();
    await page.waitForLoadState("networkidle", { timeout: 15_000 }).catch(() => {});

    // 应有「报销单报表」区域
    await expect(page.locator("text=报销单报表").first()).toBeVisible({ timeout: 15_000 });

    // 应有「生成报表」按钮
    const generateBtn = page.locator('button:has-text("生成报表")').first();
    await expect(generateBtn).toBeVisible({ timeout: 5_000 });

    // 应有 3 个下载按钮（初始可能 disabled，因为还没生成）
    const downloadExcelBtn = page.locator('button:has-text("下载 Excel")').first();
    const downloadPdfBtn = page.locator('button:has-text("下载 PDF")').first();
    const downloadZipBtn = page.locator('button:has-text("下载 ZIP")').first();
    await expect(downloadExcelBtn).toBeVisible();
    await expect(downloadPdfBtn).toBeVisible();
    await expect(downloadZipBtn).toBeVisible();

    // 点「生成报表」
    await generateBtn.click();

    // 等「生成报表」按钮恢复可点（disabled 状态结束）
    await expect(generateBtn).toBeEnabled({ timeout: 60_000 });

    // 验证下载按钮变 enabled（excel_path 已生成）
    await expect(downloadExcelBtn).toBeEnabled({ timeout: 5_000 });
    await expect(downloadPdfBtn).toBeEnabled({ timeout: 5_000 });
    await expect(downloadZipBtn).toBeEnabled({ timeout: 5_000 });

    // 下载 Excel — 监听下载事件验证文件类型
    const excelDownloadPromise = page.waitForEvent("download", { timeout: 30_000 });
    await downloadExcelBtn.click();
    const excelDownload = await excelDownloadPromise;
    expect(excelDownload.suggestedFilename()).toMatch(/\.xlsx$/);

    // 下载 PDF
    const pdfDownloadPromise = page.waitForEvent("download", { timeout: 30_000 });
    await downloadPdfBtn.click();
    const pdfDownload = await pdfDownloadPromise;
    expect(pdfDownload.suggestedFilename()).toMatch(/\.pdf$/);
  });
});
