import { expect, test } from '@playwright/test'

test('landing navigation keeps a clear mobile action without overflow', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('link', { name: 'Omniweb' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Get started' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Platform', exact: true })).toBeHidden()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

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
