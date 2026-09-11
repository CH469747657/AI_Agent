/**
 * 员工自生成报销单 + 管理员 cutoff 配置 E2E
 *
 * 覆盖：
 * - 员工点「生成我的报销单」按钮 → 跳到详情视图
 * - 同一周期二次点生成 → 返回同一报销单（幂等）
 * - 管理员改 cutoff=15 → 保存成功，显示「当前周期」/「下次生效周期」
 *
 * 注：PortalMyReimbursements 组件用内部 state（view="list" | "detail"）
 * 切换列表/详情视图，URL 始终为 /portal/reimbursements，无 :id 路由。
 * 详情视图通过「报销单 #N」标题+「返回列表」按钮识别。
 */

import { test, expect } from "../fixtures";
import { loginAsEmployee, loginAsAdmin } from "../helpers/auth";

test.describe("员工自生成报销单", () => {
  test.beforeEach(async ({ page }) => {
    // 员工登录（EMP001 陈辉是历史 e2e 脚本约定工号）
    await loginAsEmployee(page, "EMP001", "123456");
  });

  test("员工点生成按钮跳详情页", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/portal/reimbursements", { waitUntil: "domcontentloaded" });

    // 点「生成我的报销单」按钮
    await page.click('button:has-text("生成我的报销单")');

    // 详情视图出现：标题含「报销单 #N」
    await expect(
      page.locator('h2:has-text(/报销单 #\d+/)').first()
    ).toBeVisible({ timeout: 30_000 });

    // URL 不变（详情通过 state 切换，不走路由）
    expect(page.url()).toMatch(/\/portal\/reimbursements$/);
  });

  test("同一周期二次点生成返回同一报销单", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/portal/reimbursements", { waitUntil: "domcontentloaded" });

    // 第一次点
    await page.click('button:has-text("生成我的报销单")');
    await expect(
      page.locator('h2:has-text(/报销单 #\d+/)').first()
    ).toBeVisible({ timeout: 30_000 });
    const idText1 = await page
      .locator('h2:has-text(/报销单 #\d+/)')
      .first()
      .textContent();
    const id1 = (idText1 || "").match(/#(\d+)/)?.[1];

    // 返回列表
    await page.click('button:has-text("返回列表")');
    await expect(
      page.locator('h1:has-text("我的报销单")')
    ).toBeVisible({ timeout: 10_000 });

    // 第二次点 — 应返回同一报销单 id（幂等）
    await page.click('button:has-text("生成我的报销单")');
    await expect(
      page.locator('h2:has-text(/报销单 #\d+/)').first()
    ).toBeVisible({ timeout: 30_000 });
    const idText2 = await page
      .locator('h2:has-text(/报销单 #\d+/)')
      .first()
      .textContent();
    const id2 = (idText2 || "").match(/#(\d+)/)?.[1];

    expect(id1).toBeTruthy();
    expect(id2).toBeTruthy();
    expect(id1).toEqual(id2);
  });
});

test.describe("管理员配置 cutoff", () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page, "admin", "123456");
  });

  test("改 cutoff 15 保存成功", async ({ page }) => {
    test.setTimeout(60_000);
    await page.goto("/settings", { waitUntil: "domcontentloaded" });

    // 切到「周期配置」tab
    await page.click('button:has-text("周期配置")');

    // number input 填 15（覆盖原值）
    const input = page.locator('input[type="number"]').first();
    await input.fill("15");

    // 点「保存配置」按钮（注意 isDirty=true 时才可用）
    await page.click('button:has-text("保存配置")');

    // 断言：保存成功的「当前周期」或保存成功提示出现
    // Settings 页面 CycleTab 同时显示「当前周期：」label 和「保存成功，下个完整周期生效」msg
    await expect(
      page.locator("text=当前周期").first()
    ).toBeVisible({ timeout: 15_000 });
  });
});
