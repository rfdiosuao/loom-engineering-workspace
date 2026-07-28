import { expect, test } from './support/audit-fixture';

const WORKBENCHES = [
  { key: 'agents', ready: '[data-agent-page-scroll]', root: '[data-white-label-layout="installer"]' },
  { key: 'acquisition', ready: '[data-acquisition-workbench]', root: '[data-acquisition-workbench]' },
  { key: 'phone', ready: '[data-phone-page]', root: '[data-phone-page]' },
  { key: 'workbench', ready: '[data-matrix-command-bar]', root: '[data-white-label-layout="phone-matrix"]' },
  { key: 'agent', ready: '[data-agent-workbench]', root: '[data-agent-workbench]' },
  { key: 'creative', ready: '[data-creative-media-page]', root: '[data-creative-media-page]' },
  { key: 'license', ready: '[data-account-subscription-page]', root: '[data-account-subscription-page]' },
  { key: 'agentAccess', ready: '[data-agent-access-page]', root: '[data-agent-access-page]' },
  { key: 'models', ready: '[data-models-page]', root: '[data-models-page]' },
  { key: 'diagnostics', ready: '[data-diagnostics-page]', root: '[data-diagnostics-page]' },
] as const;

test.beforeEach(async ({ audit, page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await audit.openAuthorizedShell();
  await expect(page.locator('[data-loom-splash]')).toBeHidden({ timeout: 12_000 });
});

test('major workbenches share semantic canvas and surfaces in light and dark themes', async ({ audit, page }, testInfo) => {
  test.setTimeout(90_000);

  for (const theme of ['light', 'dark'] as const) {
    await page.evaluate(async (nextTheme) => {
      const [{ useAppStore }, themeRuntime] = await Promise.all([
        import('/src/stores/appStore.ts'),
        import('/src/theme/default.ts'),
      ]);
      const state = useAppStore.getState();
      const runtimeTheme = themeRuntime.buildRuntimeTheme(
        state.themeConfig ?? themeRuntime.DEFAULT_THEME,
        nextTheme,
      );
      themeRuntime.persistThemeMode(nextTheme);
      state.setThemeMode(nextTheme);
      state.setThemeConfig(runtimeTheme);
      state.setNavItems(themeRuntime.normalizeNavItems(runtimeTheme.navItems));
      themeRuntime.applyThemeToCssVars(runtimeTheme);
    }, theme);
    await expect(page.locator('html')).toHaveAttribute('data-effective-theme-mode', theme);

    for (const workbench of WORKBENCHES) {
      await test.step(`${theme}-${workbench.key}`, async () => {
        await audit.navigateTo({ key: workbench.key, readySelector: workbench.ready });
        const root = page.locator(workbench.root).first();
        await expect(root).toBeVisible();

        const metrics = await root.evaluate((element) => {
          const box = element.getBoundingClientRect();
          const surface = element.querySelector<HTMLElement>(
            '[class*="bg-surface"], [class*="bg-input"]',
          );
          return {
            background: getComputedStyle(element).backgroundColor,
            expectedBackground: getComputedStyle(document.body).backgroundColor,
            surfaceBackground: surface ? getComputedStyle(surface).backgroundColor : '',
            rootOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
            left: box.left,
            right: box.right,
            bottom: box.bottom,
            width: window.innerWidth,
            height: window.innerHeight,
          };
        });

        expect(metrics.background).toBe(metrics.expectedBackground);
        expect(metrics.surfaceBackground).not.toBe('');
        expect(metrics.surfaceBackground).not.toBe('rgba(0, 0, 0, 0)');
        expect(metrics.rootOverflow).toBeLessThanOrEqual(0);
        expect(metrics.bodyOverflow).toBeLessThanOrEqual(0);
        expect(metrics.left).toBeGreaterThanOrEqual(0);
        expect(metrics.right).toBeLessThanOrEqual(metrics.width);
        expect(metrics.bottom).toBeLessThanOrEqual(metrics.height);

        await page.screenshot({
          path: testInfo.outputPath(`${theme}-${workbench.key}-color-cohesion.png`),
          fullPage: false,
        });
      });
    }
  }
});

test('acquisition status indicators use semantic tone styling', async ({ audit, page }) => {
  await audit.navigateTo({ key: 'acquisition', readySelector: '[data-acquisition-workbench]' });
  const indicators = page.locator('[data-status-tone]');
  await expect(indicators.first()).toBeVisible();
  expect(await indicators.count()).toBeGreaterThanOrEqual(2);

  for (const indicator of await indicators.all()) {
    const metrics = await indicator.evaluate((element) => {
      const style = getComputedStyle(element);
      return {
        tone: element.getAttribute('data-status-tone'),
        background: style.backgroundColor,
        foreground: style.color,
        border: style.borderColor,
      };
    });
    expect(['neutral', 'info', 'success', 'warning', 'danger']).toContain(metrics.tone);
    expect(metrics.background).not.toBe('rgba(0, 0, 0, 0)');
    expect(metrics.foreground).not.toBe(metrics.background);
    expect(metrics.border).not.toBe('rgba(0, 0, 0, 0)');
  }
});
