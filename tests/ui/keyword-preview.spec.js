const { test, expect } = require('@playwright/test');


test('keyword preview chips preserve keyword data attributes', async ({ page }) => {
  await page.route('**/keywords', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ keywords: [], manual: [], graph: [], total: 0 }),
  }));

  await page.route('**/ingest/preview', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      preview_id: 'test-preview',
      url: 'https://example.com',
      keywords: {
        existing: ['python'],
        new: ['retrieval'],
      },
    }),
  }));

  await page.goto('/');
  await page.locator('input[name="url"]').fill('https://example.com');
  await page.locator('#ingest-btn').click();

  await expect(page.locator('#keyword-preview')).toHaveClass(/visible/);
  await expect(page.locator('.kw-chip.existing')).toHaveAttribute('data-keyword', 'python');
  await expect(page.locator('.kw-chip.new')).toHaveAttribute('data-keyword', 'retrieval');
  await expect(page.locator('.kw-chip.new input')).toHaveAttribute('data-keyword', 'retrieval');
});


test('unchecked suggested keywords are not submitted', async ({ page }) => {
  let submittedPayload;

  await page.route('**/keywords', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ keywords: [], manual: [], graph: [], total: 0 }),
  }));

  await page.route('**/ingest/preview', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      preview_id: 'test-preview',
      url: 'https://example.com',
      keywords: { existing: ['python'], new: ['retrieval'] },
    }),
  }));

  await page.route('**/ingest/run', async route => {
    submittedPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ job_id: 'test-job' }),
    });
  });

  await page.route('**/stream/**', route => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'event: done\ndata: {}\n\n',
  }));

  await page.goto('/');
  await page.locator('input[name="url"]').fill('https://example.com');
  await page.locator('#ingest-btn').click();
  await page.locator('.kw-chip.new input').uncheck();
  await page.locator('#confirm-btn').click();

  await expect.poll(() => submittedPayload).toEqual(expect.objectContaining({
    accepted_keywords: [],
  }));
});
