import { expect, test } from './support/audit-fixture';

test.beforeEach(async ({ audit }) => {
  await audit.openAuthorizedShell();
});

async function openConfirmation(page: import('@playwright/test').Page) {
  await page.evaluate(async () => {
    const commonModulePath: string = '/src/components/common/index.tsx';
    const { showConfirm } = await import(commonModulePath) as {
      showConfirm: (options: {
        title: string;
        message: string;
        confirmText: string;
        cancelText: string;
      }) => Promise<boolean>;
    };
    void showConfirm({
      title: 'Accessibility confirmation',
      message: 'Confirm that keyboard users can safely respond.',
      confirmText: 'Confirm action',
      cancelText: 'Keep editing',
    });
  });

  return page.getByRole('dialog', { name: 'Accessibility confirmation' });
}

test('confirmation dialog closes with Escape and restores focus', async ({ page }) => {
  const opener = page.locator('[data-commercial-app-shell] aside button').first();
  await opener.focus();
  await expect(opener).toBeFocused();

  const dialog = await openConfirmation(page);
  await expect(dialog).toBeVisible();
  await page.keyboard.press('Escape');

  await expect(dialog).toBeHidden();
  await expect(opener).toBeFocused();
});

test('confirmation dialog focuses cancel and traps sequential focus', async ({ page }) => {
  const dialog = await openConfirmation(page);
  const cancel = dialog.getByRole('button', { name: 'Keep editing' });
  const confirm = dialog.getByRole('button', { name: 'Confirm action' });

  await expect(cancel).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(confirm).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(cancel).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(confirm).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(cancel).toBeFocused();
});

test('toast message is exposed as an atomic polite status', async ({ page }) => {
  await page.evaluate(async () => {
    const commonModulePath: string = '/src/components/common/index.tsx';
    const { showToast } = await import(commonModulePath) as {
      showToast: (message: string, type: 'success' | 'error' | 'info') => void;
    };
    showToast('Accessible notification', 'success');
  });

  const status = page.getByRole('status').filter({ hasText: 'Accessible notification' });
  await expect(status).toHaveAttribute('aria-live', 'polite');
  await expect(status).toHaveAttribute('aria-atomic', 'true');
});
