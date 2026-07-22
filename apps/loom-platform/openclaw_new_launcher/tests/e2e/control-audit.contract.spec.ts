import { expect, PAGE_REGISTRY, test } from './support/audit-fixture';
import { pageControls, shellControls } from './support/control-audit';

const BASELINE_CONTROL_COUNTS: Record<string, number> = {
  dashboard: 2,
  agents: 15,
  creative: 19,
  acquisition: 10,
  phone: 22,
  workbench: 11,
  agent: 7,
  license: 6,
  agentAccess: 2,
  capabilities: 0,
  settings: 8,
  models: 9,
  diagnostics: 5,
  terminal: 5,
};

test.beforeEach(async ({ audit }) => {
  await audit.openAuthorizedShell();
});

test('locks the global shell and 14-page visible control inventory', async ({ audit, page }) => {
  await expect(shellControls(page), 'global shell controls').toHaveCount(13);

  for (const entry of PAGE_REGISTRY) {
    await test.step(entry.key, async () => {
      await audit.navigateTo(entry);
      await expect(
        pageControls(page),
        `Visible actionable controls changed on ${entry.key}; add an action audit before updating this count`,
      ).toHaveCount(BASELINE_CONTROL_COUNTS[entry.key]);
    });
  }
});

test('classifies intentional unavailable states with truthful explanations', async ({ audit, page }) => {
  await audit.navigateTo(PAGE_REGISTRY.find(({ key }) => key === 'agents')!);
  const lockedModelConfig = page.locator('[data-agent-one-click-config-lock]');
  await expect(lockedModelConfig).toBeDisabled();
  await expect(lockedModelConfig)
    .toHaveAttribute('title', '登录后解锁：请先同步托管模型');

  await audit.navigateTo(PAGE_REGISTRY.find(({ key }) => key === 'workbench')!);
  await expect(page.getByRole('button', { name: '下发任务' })).toBeDisabled();
  await expect(page.getByText('没有匹配的真实设备')).toBeVisible();
  await expect(page.getByText('调整分组或搜索条件')).toBeVisible();

  const emergencyStop = page.getByRole('button', { name: '急停' });
  await expect(emergencyStop).toBeDisabled();
  await expect(emergencyStop).toHaveAttribute('title', '当前没有运行中或排队任务');

  await audit.navigateTo(PAGE_REGISTRY.find(({ key }) => key === 'diagnostics')!);
  await expect(page.getByRole('button', { name: '无可修复项' })).toBeDisabled();
});
