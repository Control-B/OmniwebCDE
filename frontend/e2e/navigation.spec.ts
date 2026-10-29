import { expect, test } from '@playwright/test'

test('landing navigation exposes arrow-free accessible mega menus', async ({ page }) => {
  await page.goto('/')

  const product = page.getByRole('button', { name: 'Product', exact: true })
  const solutions = page.getByRole('button', { name: 'Solutions', exact: true })
  const resources = page.getByRole('button', { name: 'Resources', exact: true })

  await expect(product.locator('svg')).toHaveCount(0)
  await expect(solutions.locator('svg')).toHaveCount(0)
  await expect(resources.locator('svg')).toHaveCount(0)

  await product.hover()
  await expect(page.getByRole('link', { name: /^Unified Create/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /Marketing Studio/ })).toBeVisible()

  await solutions.hover()
  await expect(page.getByRole('link', { name: /Founders/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /Marketing teams/ })).toBeVisible()

  await resources.hover()
  await expect(page.getByRole('link', { name: /How it works/ })).toBeVisible()
  await expect(page.getByRole('link', { name: /About Omniweb/ })).toBeVisible()

  await page.getByRole('link', { name: 'Omniweb' }).focus()
  await page.keyboard.press('Tab')
  await expect(product).toBeFocused()
  await expect(page.getByRole('link', { name: /^Unified Create/ })).toBeVisible()

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
