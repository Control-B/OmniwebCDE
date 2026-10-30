import { expect, test } from '@playwright/test'

test('unified create shows risk, required approvals, and evidence-backed quality records', async ({ page }) => {
  test.setTimeout(90_000)
  await page.goto('/create')
  await page.getByRole('textbox').fill(
    `Create a business plan for a mobile bike repair service in the US and write social posts, then publish them. E2E ${Date.now()}`,
  )
  await page.getByRole('button', { name: /Create plan/ }).click()

  const assessment = page.getByRole('region', { name: 'Risk and approval assessment' })
  await expect(assessment).toContainText('moderate risk')
  await expect(assessment).toContainText('External publication')

  const records = page.locator('.growth-quality')
  await expect(records).toHaveCount(2, { timeout: 45_000 })
  await records.first().locator('summary').click()
  await expect(records.first()).toContainText('Verification')
  await expect(records.first()).toContainText('Awaiting approval')
  await expect(page.locator('.growth-task .st-pill', { hasText: /verified|approved|deployed/ })).toHaveCount(0)
})
