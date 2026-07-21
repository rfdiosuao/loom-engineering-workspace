import { expect, PAGE_REGISTRY, test } from './support/audit-fixture';

test.beforeEach(async ({ audit }) => {
  await audit.openAuthorizedShell();
});
test('navigates the complete page registry inside the global shell', async ({ audit, page }) => {
  await expect(page.locator('[data-window-drag-above-overlays]')).toBeVisible();
  await expect(page.locator('[data-commercial-app-shell]')).toBeVisible();
  await expect(page.locator('aside')).toBeVisible();
  await expect(page.locator('main')).toBeVisible();

  for (const entry of PAGE_REGISTRY) {
    await test.step(entry.key, async () => {
      await audit.navigateTo(entry);
      await expect(page.locator(entry.readySelector).first()).toBeVisible();
    });
  }

  await audit.sync();
  expect(audit.callLogs.length).toBeGreaterThan(0);
  expect(audit.consoleErrors).toEqual([]);
  expect(audit.unexpectedCommandFailures).toEqual([]);
});

test('keeps every registry page within a stable viewport without horizontal overflow', async ({ audit, page }) => {
  const expectedViewport = page.viewportSize();
  expect(expectedViewport).not.toBeNull();

  for (const entry of PAGE_REGISTRY) {
    await test.step(entry.key, async () => {
      await audit.navigateTo(entry);
      const metrics = await page.evaluate(() => {
        const root = document.documentElement;
        const body = document.body;
        const shell = document.querySelector<HTMLElement>('[data-commercial-app-shell]');
        return {
          width: window.innerWidth,
          height: window.innerHeight,
          rootOverflow: root.scrollWidth - root.clientWidth,
          bodyOverflow: body.scrollWidth - body.clientWidth,
          shellRight: shell?.getBoundingClientRect().right ?? 0,
          shellBottom: shell?.getBoundingClientRect().bottom ?? 0,
        };
      });

      expect(metrics.width).toBe(expectedViewport?.width);
      expect(metrics.height).toBe(expectedViewport?.height);
      expect(metrics.rootOverflow).toBeLessThanOrEqual(0);
      expect(metrics.bodyOverflow).toBeLessThanOrEqual(0);
      expect(metrics.shellRight).toBeLessThanOrEqual(metrics.width);
      expect(metrics.shellBottom).toBeLessThanOrEqual(metrics.height);
    });
  }
});

test('preserves accessible names on baseline button controls', async ({ audit, page }) => {
  for (const name of ['最小化', '最大化/还原', '关闭']) {
    await expect(page.getByRole('button', { name, exact: true })).toBeVisible();
  }

  for (const entry of PAGE_REGISTRY) {
    await test.step(entry.key, async () => {
      await audit.navigateTo(entry);
      const unnamedButtons = await page.locator('button:visible').evaluateAll((buttons) => buttons
        .filter((button) => {
          const element = button as HTMLElement;
          const name = element.getAttribute('aria-label')
            || element.getAttribute('title')
            || element.textContent;
          return !name?.trim();
        })
        .map((button) => button.outerHTML.slice(0, 180)));

      expect(unnamedButtons, `Unnamed buttons on ${entry.key}`).toEqual([]);
    });
  }
});
