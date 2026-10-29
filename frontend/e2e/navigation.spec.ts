import { expect, test } from '@playwright/test'

test('landing navigation exposes arrow-free accessible mega menus', async ({ page }) => {
  await page.goto('/')

  const platform = page.getByRole('button', { name: 'Platform', exact: true })
  const solutions = page.getByRole('button', { name: 'Solutions', exact: true })
  const developers = page.getByRole('button', { name: 'Developers', exact: true })
  const resources = page.getByRole('button', { name: 'Resources', exact: true })

  await expect(platform.locator('svg')).toHaveCount(0)
  await expect(solutions.locator('svg')).toHaveCount(0)
  await expect(developers.locator('svg')).toHaveCount(0)
  await expect(resources.locator('svg')).toHaveCount(0)

  await platform.hover()
  await expect(page.getByRole('link', { name: /^Unified Create/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /Marketing Studio/ })).toBeVisible()

  await solutions.hover()
  await expect(page.getByRole('link', { name: /Founders/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /Marketing teams/ })).toBeVisible()

  await developers.hover()
  await expect(page.getByRole('link', { name: /Platform overview/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /MCP integrations/ })).toBeVisible()

  await resources.hover()
  await expect(page.getByRole('link', { name: /^Templates/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /Trust & security/ })).toBeVisible()

  await page.getByRole('link', { name: 'Omniweb', exact: true }).focus()
  await page.keyboard.press('Tab')
  await expect(platform).toBeFocused()
  await expect(page.getByRole('link', { name: /^Unified Create/ })).toBeVisible()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('every navigation item opens a dedicated marketing page', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Platform', exact: true }).hover()
  await page.getByRole('link', { name: /^Business Planner/ }).click()
  await expect(page).toHaveURL(/\/explore\/business-planner$/)
  await expect(page.getByRole('heading', { name: 'Business Planner', level: 1 })).toBeVisible()
  await expect(page.getByText('From brief to verified outcome.')).toBeVisible()
  await expect(page.getByRole('link', { name: /Start with Unified Create/ })).toBeVisible()
})
