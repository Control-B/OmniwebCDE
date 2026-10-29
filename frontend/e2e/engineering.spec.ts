import { expect, test } from '@playwright/test'

test('generates, previews, validates, and revises a real engineering design', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/projects')
  const href = await page.locator('.st-project').first().getAttribute('href')
  expect(href).toMatch(/\/projects\/[0-9a-f-]+/)
  const projectId = href!.split('/')[2].split('?')[0]
  await page.goto(`/projects/${projectId}/engineering`)

  await expect(page.getByRole('heading', { name: 'Engineering Design' })).toBeVisible()
  await page.getByRole('button', { name: 'Play Engineering CAD workspace walkthrough' }).click()
  const walkthrough = page.getByRole('dialog', { name: 'Engineering CAD workspace walkthrough' })
  await expect(walkthrough).toBeVisible()
  await expect(walkthrough.locator('video')).toHaveAttribute('poster', '/media/engineering-cad-workspace-poster.jpg')
  await expect(walkthrough.locator('source')).toHaveAttribute('src', '/media/engineering-cad-workspace-walkthrough.mp4')
  await page.getByRole('button', { name: 'Close walkthrough' }).click()
  await expect(walkthrough).toBeHidden()
  await page.getByLabel('Describe the mechanical component').fill(
    `Design an L-shaped steel mounting bracket, 200 mm long, 80 mm wide, 6 mm thick, with four 10 mm mounting holes. E2E ${Date.now()}`,
  )
  await page.getByRole('button', { name: 'Generate design' }).click()

  await expect(page.locator('.eng-state')).toContainText('validated', { timeout: 30_000 })
  await expect(page.getByLabel('Interactive 3D model').locator('canvas')).toBeVisible()
  await expect(page.locator('.eng-check', { hasText: /brep valid/i })).toContainText('valid')
  await expect(page.locator('.eng-exports button', { hasText: 'STEP' })).toBeVisible()
  await expect(page.locator('.eng-safety')).toContainText('not structural analysis')

  const thickness = page.getByRole('spinbutton', { name: 'thickness mm', exact: true })
  await thickness.fill('8')
  await page.getByLabel('Revision note').fill('Increase plate thickness to 8 mm')
  await page.getByRole('button', { name: 'Create immutable revision' }).click()
  await expect(page.locator('.eng-design-head')).toContainText('Revision 2', { timeout: 30_000 })
  await expect(page.locator('.eng-state')).toContainText('validated', { timeout: 30_000 })
  await expect(page.locator('.eng-revisions > div')).toHaveCount(2)
})

test('builds assemblies, estimates manufacturing, and runs screening simulations', async ({ page }) => {
  test.setTimeout(120_000)
  await page.goto('/projects')
  const href = await page.locator('.st-project').first().getAttribute('href')
  const projectId = href!.split('/')[2].split('?')[0]
  await page.goto(`/projects/${projectId}/engineering`)

  await page.getByRole('button', { name: 'Assemblies', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'CAD assemblies' })).toBeVisible()
  await page.getByRole('button', { name: 'Generate assembly' }).click()
  await expect(page.locator('.eng-result-title')).toContainText('validated', { timeout: 30_000 })
  await expect(page.locator('.eng-assembly-view canvas')).toBeVisible()
  await expect(page.locator('.eng-bom > div')).toHaveCount(2)
  await expect(page.locator('.eng-exports button', { hasText: 'STEP' })).toBeVisible()

  await page.getByRole('button', { name: 'Manufacturing', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Manufacturing estimates' })).toBeVisible()
  await page.getByRole('button', { name: 'Calculate estimate' }).click()
  await expect(page.getByRole('heading', { name: 'Budgetary manufacturing estimate' })).toBeVisible()
  await expect(page.locator('.eng-estimate-total')).toContainText('$')
  await expect(page.locator('.eng-safety')).toContainText('not a supplier quote')

  await page.getByRole('button', { name: 'Simulations', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Simulations' })).toBeVisible()
  await page.getByRole('button', { name: 'Run screening' }).click()
  await expect(page.getByRole('heading', { name: 'Screening results' })).toBeVisible()
  await expect(page.locator('.eng-simulation-results article').first()).toBeVisible()
  await expect(page.locator('.eng-safety')).toContainText('not finite-element analysis')
})
