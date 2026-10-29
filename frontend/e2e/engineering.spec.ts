import { expect, test } from '@playwright/test'

test('generates, previews, validates, and revises a real engineering design', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/projects')
  const href = await page.locator('.st-project').first().getAttribute('href')
  expect(href).toMatch(/\/projects\/[0-9a-f-]+/)
  const projectId = href!.split('/')[2].split('?')[0]
  await page.goto(`/projects/${projectId}/engineering`)

  await expect(page.getByRole('heading', { name: 'Engineering Design' })).toBeVisible()
  await page.getByLabel('Describe the mechanical component').fill(
    `Design an L-shaped steel mounting bracket, 200 mm long, 80 mm wide, 6 mm thick, with four 10 mm mounting holes. E2E ${Date.now()}`,
  )
  await page.getByRole('button', { name: 'Generate design' }).click()

  await expect(page.locator('.eng-state')).toContainText('validated', { timeout: 30_000 })
  await expect(page.getByLabel('Interactive 3D model').locator('canvas')).toBeVisible()
  await expect(page.locator('.eng-check', { hasText: /brep validity/i })).toContainText('valid')
  await expect(page.locator('.eng-exports button', { hasText: 'STEP' })).toBeVisible()
  await expect(page.locator('.eng-safety')).toContainText('not structural analysis')

  const thickness = page.locator('.eng-parameter-grid label', { hasText: 'thickness' }).locator('input')
  await thickness.fill('8')
  await page.getByLabel('Revision note').fill('Increase plate thickness to 8 mm')
  await page.getByRole('button', { name: 'Create immutable revision' }).click()
  await expect(page.locator('.eng-design-head')).toContainText('Revision 2', { timeout: 30_000 })
  await expect(page.locator('.eng-state')).toContainText('validated', { timeout: 30_000 })
  await expect(page.locator('.eng-revisions > div')).toHaveCount(2)
})
