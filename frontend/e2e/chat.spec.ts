import { expect, test } from "@playwright/test";

test("流式回答、来源、刷新历史、独立会话与停止生成", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "输入问题" })).toBeEnabled();
  // 每次运行使用新会话，避免上一次验收留下的历史影响断言。
  await page.getByRole("button", { name: /新建对话/ }).click();
  await expect(page.locator(".assistant-message")).toHaveCount(0);
  // 欢迎内容只在消息区滚动，避免桌面输入框被挤出屏幕。
  const composer = await page.locator(".composer").boundingBox();
  expect(composer).not.toBeNull();
  expect(composer!.y + composer!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
  await page.screenshot({ path: "test-results/desktop.png", fullPage: true });
  await page.getByRole("textbox", { name: "输入问题" }).fill("根据我的手册，冷却液多久更换？");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.locator(".assistant-message").last()).toContainText("九天");
  await expect(page.getByRole("button", { name: "停止生成", exact: true })).toHaveCount(0);
  await page.locator(".source-chips button").last().click();
  await expect(page.locator(".source-card")).toContainText("星舟设备冷却液每九天更换一次");
  await page.reload();
  await expect(page.locator(".assistant-message").last()).toContainText("九天");
  await page.getByRole("button", { name: /新建对话/ }).click();
  await expect(page.locator(".assistant-message")).toHaveCount(0);
  await page.getByRole("textbox", { name: "输入问题" }).fill("请测试停止生成");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await expect(page.locator(".assistant-message").last()).toContainText("部分回答");
  await page.getByRole("button", { name: "停止生成", exact: true }).click();
  await expect(page.locator(".message-warning").last()).toContainText("已停止");
  await page.reload();
  await expect(page.locator(".message-warning").last()).toContainText("已停止");
  expect(errors).toEqual([]);
});

test("资料上传、明确确认删除与移动布局", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("textbox", { name: "输入问题" })).toBeEnabled();
  await page.getByLabel("上传资料").setInputFiles({ name: "浏览器合成.md", mimeType: "text/markdown", buffer: Buffer.from("# 合成资料\n配置每天凌晨三点备份，保留十四天。") });
  await page.getByRole("button", { name: "导入 / 更新资料", exact: true }).click();
  const documentRow = page.locator(".document-row").filter({ hasText: "浏览器合成.md" });
  await expect(documentRow).toBeVisible();
  await documentRow.getByRole("checkbox").check();
  await expect(page.getByRole("button", { name: "删除所选资料" })).toBeDisabled();
  await page.getByRole("checkbox", { name: "已核对，确认移入回收站" }).check();
  await page.getByRole("button", { name: "删除所选资料" }).click();
  await expect(documentRow).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "test-results/mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});
