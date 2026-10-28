import { expect, test } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

test('generates an app from the landing page, previews it, and applies a chat edit', async ({ page }) => {
  test.setTimeout(180_000)
  await page.goto('/')
  const appTab = page.getByRole('tab', { name: 'Full-stack app' })
  await expect(async () => {
    await appTab.click()
    await expect(appTab).toHaveAttribute('aria-selected', 'true', { timeout: 500 })
  }).toPass()
  await page.getByLabel('Describe the application you want to build').fill(`A tool library ${Date.now()} where neighbours lend and borrow tools`)
  await page.getByRole('button', { name: 'Create application' }).click()
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+/)

  await expect(page.locator('.rc').first()).toBeVisible({ timeout: 15_000 })
  const preview = page.locator('iframe[title="App preview"]')
  await expect(preview).toBeVisible({ timeout: 120_000 })
  await expect(preview.contentFrame().locator('h1').first()).toBeVisible({ timeout: 15_000 })
  await expect(page.locator('.st-status')).toContainText(/ready/i)

  await page.getByRole('tab', { name: 'Logs' }).click()
  await expect(page.locator('.lg-step[data-ok="true"]').first()).toBeVisible()
  await expect(page.locator('.lg-step[data-ok="false"]')).toHaveCount(0)

  await page.getByRole('tab', { name: 'Files' }).click()
  await expect(page.locator('.cp-file').first()).toBeVisible()
  await expect(page.locator('.monaco-editor').first()).toBeVisible({ timeout: 20_000 })

  await page.getByRole('tab', { name: 'Database' }).click()
  await expect(page.locator('.mg-list li').first()).toBeVisible()

  await page.getByLabel('Ask the builder for a change').fill('Tools should have a brand')
  await page.getByLabel('Ask the builder for a change').press('Enter')
  await expect(page.locator('.bd-msg-user', { hasText: 'brand' })).toBeVisible()
  await expect(page.locator('.bd-msg-assistant', { hasText: 'Added Brand to Tools' })).toBeVisible({ timeout: 120_000 })
  await expect(page.locator('.st-status')).toContainText(/ready/i, { timeout: 30_000 })

  await page.getByRole('tab', { name: 'Changes' }).click()
  await expect(page.locator('.hp-list > li')).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Undo' })).toBeEnabled()
})

test('builder panels collapse, expand and go full screen', async ({ page }) => {
  await page.goto('/projects')
  await page.locator('.st-project').first().click()
  await expect(page.getByRole('region', { name: 'Conversation and progress' })).toBeVisible()

  await page.getByTitle('Hide conversation panel').click()
  await expect(page.getByRole('region', { name: 'Conversation and progress' })).toBeHidden()
  await page.getByTitle('Show conversation panel').click()
  await expect(page.getByRole('region', { name: 'Conversation and progress' })).toBeVisible()

  await page.getByTitle('Hide project panel').click()
  await expect(page.getByRole('region', { name: 'Project details' })).toBeHidden()
  await page.getByTitle('Show project panel').click()

  await page.getByTitle('Full-screen preview').click()
  await expect(page.locator('.st-fullscreen')).toBeVisible()
  await page.getByTitle('Exit full screen').click()
  await expect(page.locator('.st-fullscreen')).toHaveCount(0)
})

test('environment variables are write-only', async ({ page }) => {
  await page.goto('/projects')
  await page.locator('.st-project').first().click()
  await page.getByRole('tab', { name: 'Environment' }).click()
  const key = `E2E_${Date.now()}`
  await page.getByLabel('Variable name').fill(key)
  await page.getByLabel('Variable value').fill('super-secret-value')
  await page.getByRole('button', { name: 'Add' }).click()
  await expect(page.locator('.st-env', { hasText: key })).toBeVisible()
  await expect(page.getByText('super-secret-value')).toHaveCount(0)
  await page.getByTitle(`Delete ${key}`).click()
  await expect(page.locator('.st-env', { hasText: key })).toHaveCount(0)
})

test('usage page lists providers, tiers and the model registry', async ({ page }) => {
  await page.goto('/usage')
  for (const name of ['OpenAI', 'Anthropic', 'Google Gemini', 'OpenRouter', 'Ollama']) {
    await expect(page.locator('#providers .st-provider-head', { hasText: name }).first()).toBeVisible()
  }
  await expect(page.locator('#pricing')).toContainText('Your own keys')
  await expect(page.locator('.st-table tbody tr').first()).toBeVisible()
})
