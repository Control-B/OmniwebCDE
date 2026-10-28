import { expect, test } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

test('creates an app project from the landing page and gets a requirements reply', async ({ page }) => {
  await page.goto('/')
  const appTab = page.getByRole('tab', { name: 'Full-stack app' })
  await expect(async () => {
    await appTab.click()
    await expect(appTab).toHaveAttribute('aria-selected', 'true', { timeout: 500 })
  }).toPass()
  const name = `Tool library ${Date.now()}`
  await page.getByLabel('Describe the application you want to build').fill(`${name} where neighbours lend and borrow tools`)
  await page.getByRole('button', { name: 'Create application' }).click()

  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]+/)
  await expect(page.locator('.bd-msg-user').first()).toContainText('lend and borrow tools')
  await expect(page.locator('.bd-msg-assistant .st-msg-meta').first()).toBeVisible({ timeout: 30_000 })

  await page.getByRole('tab', { name: 'Progress' }).click()
  await expect(page.locator('.st-run').first()).toContainText('Requirements agent')
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
