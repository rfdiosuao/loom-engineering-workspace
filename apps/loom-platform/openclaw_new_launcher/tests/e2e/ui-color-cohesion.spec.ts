import { expect, test } from './support/audit-fixture';

const WORKBENCHES = [
  { key: 'agents', ready: '[data-agent-page-scroll]', root: '[data-white-label-layout="installer"]', region: '[data-agent-page-scroll]' },
  { key: 'acquisition', ready: '[data-acquisition-workbench]', root: '[data-acquisition-workbench]', region: '[data-acquisition-hero]' },
  { key: 'phone', ready: '[data-phone-page]', root: '[data-phone-page]', region: '[data-phone-page] header' },
  { key: 'workbench', ready: '[data-matrix-command-bar]', root: '[data-white-label-layout="phone-matrix"]', region: '[data-matrix-command-bar]' },
  { key: 'agent', ready: '[data-agent-workbench]', root: '[data-agent-workbench]', region: '[data-agent-workbench] main' },
  { key: 'creative', ready: '[data-creative-media-page]', root: '[data-creative-media-page]', region: '[data-creative-media-page] header' },
  { key: 'license', ready: '[data-account-subscription-page]', root: '[data-account-subscription-page]', region: '[data-account-subscription-page] header' },
  { key: 'agentAccess', ready: '[data-agent-access-page]', root: '[data-agent-access-page]', region: '[data-agent-access-page] header' },
  { key: 'models', ready: '[data-models-page]', root: '[data-models-page]', region: '[data-models-page] header' },
  { key: 'diagnostics', ready: '[data-diagnostics-page]', root: '[data-diagnostics-page]', region: '[data-diagnostics-page] > .bg-surface' },
] as const;

test.beforeEach(async ({ audit, page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await audit.openAuthorizedShell();
  await expect(page.locator('[data-loom-splash]')).toBeHidden({ timeout: 12_000 });
});

test('major workbenches share semantic canvas, surfaces, and unclipped controls in light and dark themes', async ({ audit, page }) => {
  test.setTimeout(90_000);

  for (const theme of ['light', 'dark'] as const) {
    await page.evaluate(async (nextTheme) => {
      const storePath = '/src/stores/appStore.ts';
      const themePath = '/src/theme/default.ts';
      const [storeModule, themeModule] = await Promise.all([
        import(storePath),
        import(themePath),
      ]);
      const { useAppStore } = storeModule as {
        useAppStore: {
          getState: () => {
            themeConfig?: unknown;
            setThemeMode: (mode: 'light' | 'dark') => void;
            setThemeConfig: (config: { navItems: unknown }) => void;
            setNavItems: (items: unknown) => void;
          };
        };
      };
      const themeRuntime = themeModule as {
        DEFAULT_THEME: unknown;
        buildRuntimeTheme: (config: unknown, mode: 'light' | 'dark') => { navItems: unknown };
        persistThemeMode: (mode: 'light' | 'dark') => void;
        normalizeNavItems: (items: unknown) => unknown;
        applyThemeToCssVars: (config: { navItems: unknown }) => void;
      };
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
        const region = page.locator(workbench.region).first();
        await expect(root).toBeVisible();
        await expect(region).toBeVisible();

        const metrics = await root.evaluate((element, regionSelector) => {
          const box = element.getBoundingClientRect();
          const region = document.querySelector<HTMLElement>(regionSelector);
          const rootStyle = getComputedStyle(element);
          const regionStyle = region ? getComputedStyle(region) : null;
          const semanticBackgroundClass = region
            ? [...region.classList].find((name) => /^bg-(?:app-bg|surface(?:-(?:alt|deep|deeper))?|input)(?:\/\d+)?$/.test(name)) || ''
            : '';
          const visibleActions = [...element.querySelectorAll<HTMLElement>(
            'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary',
          )].filter((action) => {
            const actionBox = action.getBoundingClientRect();
            const style = getComputedStyle(action);
            return style.display !== 'none' && style.visibility !== 'hidden'
              && actionBox.width > 0 && actionBox.height > 0;
          });
          const clippedActions = visibleActions.filter((action) => {
            const actionBox = action.getBoundingClientRect();
            return action.scrollWidth > action.clientWidth + 2
              || actionBox.left < box.left - 1
              || actionBox.right > box.right + 1;
          }).map((action) => action.getAttribute('aria-label') || action.textContent?.trim() || action.tagName);
          return {
            background: rootStyle.backgroundColor,
            expectedBackground: getComputedStyle(document.body).backgroundColor,
            appBackgroundToken: getComputedStyle(document.documentElement).getPropertyValue('--color-app-bg').trim(),
            regionBackground: regionStyle?.backgroundColor || '',
            semanticBackgroundClass,
            rootOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
            bodyOverflow: document.body.scrollWidth - document.body.clientWidth,
            hiddenScrollableRoot: rootStyle.overflowY === 'hidden' && element.scrollHeight > element.clientHeight + 2,
            clippedActions,
            left: box.left,
            right: box.right,
            width: window.innerWidth,
          };
        }, workbench.region);

        expect(metrics.background).toBe(metrics.expectedBackground);
        expect(metrics.appBackgroundToken).not.toBe('');
        expect(metrics.regionBackground).not.toBe('');
        expect(metrics.regionBackground).not.toBe('rgba(0, 0, 0, 0)');
        expect(metrics.semanticBackgroundClass).not.toBe('');
        expect(metrics.rootOverflow).toBeLessThanOrEqual(0);
        expect(metrics.bodyOverflow).toBeLessThanOrEqual(0);
        expect(metrics.hiddenScrollableRoot).toBe(false);
        expect(metrics.clippedActions).toEqual([]);
        expect(metrics.left).toBeGreaterThanOrEqual(0);
        expect(metrics.right).toBeLessThanOrEqual(metrics.width);
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
