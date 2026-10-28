import { expect, test } from '@playwright/test'

test('builder shows one pane at a time on phones', async ({ page }) => {
  await page.goto('/projects')
  await page.locator('.st-project').first().click()
  await expect(page.getByRole('region', { name: 'Conversation and progress' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Preview' })).toHaveCount(0)

  await page.getByRole('tab', { name: 'Preview' }).click()
  await expect(page.getByRole('region', { name: 'Preview' })).toBeVisible()
  await expect(page.getByRole('region', { name: 'Conversation and progress' })).toHaveCount(0)

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
