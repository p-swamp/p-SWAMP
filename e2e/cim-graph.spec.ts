import { test, expect, type Page } from '@playwright/test'

/**
 * The CIM graph page: the grid on its geographic layout, with a breaker and a line to click. The
 * graph is shared (every visitor and the grid simulation see one), so the spec puts back what it
 * changes, and asks for no initial state: Nordic44 starts with open breakers and lines out. Edits need the CGMES profiles; where the server could not get them the graph is
 * read-only and the spec skips (the page says so).
 *
 * Runs against the grid the server was started with (the three-substation grid in CI:
 * PSWAMP_CIM_PATH, see .github/workflows/quality-checks.yml) or Nordic44 locally, so it asks for no
 * names in particular: the first breaker, the first line.
 */

const breakers = (page: Page) => page.locator('[data-testid^="breaker-"]')
const lines = (page: Page) => page.locator('[data-testid^="line-"]')

async function open(page: Page) {
  await page.goto('/cim-graph')
  // the first visit loads the graph, which can take a while (a store to fill, profiles to fetch)
  await expect(page.getByText('Online', { exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(lines(page).first()).toBeVisible({ timeout: 30_000 })
  test.skip(await page.getByText('The graph is read-only').isVisible(), 'the graph has no CGMES profiles')
  // the graph is shared and outlives a test: start from the grid as it was loaded
  await reset(page)
}

/** Reset the grid, and wait until the server has done it (its state reaches the page before the reply does). */
async function reset(page: Page) {
  const done = page.waitForResponse((r) => r.url().includes('/api/cim-graph/reset') && r.ok())
  await page.getByRole('button', { name: 'Reset grid' }).click()
  await done
}

// One graph for everyone: these tests change it, so they run one after the other.
test.describe.configure({ mode: 'serial' })
// An edit goes to the store and back (the first one also opens the schema), then down the socket.
test.use({ actionTimeout: 15_000 })
expect.configure({ timeout: 15_000 })

test.describe('CIM graph', () => {
  test('draws the grid on its layout, with its state', async ({ page }) => {
    await open(page)
    expect(await lines(page).count()).toBeGreaterThanOrEqual(3)
    expect(await breakers(page).count()).toBeGreaterThanOrEqual(1)
    await expect(page.getByText(/^\d+ open · \d+ out of service$/)).toBeVisible()
    await expect(page.getByTestId('cim-status')).toContainText('Graph: ready')
    // hover anything for its name, and what it is
    await expect(breakers(page).first().locator('title')).toContainText('(breaker, ')
    await expect(lines(page).first().locator('title')).toContainText(/service/)
  })

  test('clicking a breaker opens it, and again closes it', async ({ page }) => {
    await open(page)
    const breaker = breakers(page).first()
    const was = (await breaker.getAttribute('data-open')) === 'true' // the grid's own state: some models start with open breakers
    // dispatch on the element: on a dense grid a neighbouring substation's marker can sit over this one
    await breaker.dispatchEvent('click')
    await expect(breaker).toHaveAttribute('data-open', String(!was))
    // switching until the graph says so, then the round trip is in the status bar
    await expect(breaker).toHaveAttribute('data-pending', 'false')
    await expect(page.getByTestId('cim-status')).toContainText(/Last click: \d+ ms from click to screen/)
    await breaker.dispatchEvent('click')
    await expect(breaker).toHaveAttribute('data-open', String(was))
  })

  test('clicking a line takes it out of service, and again brings it back', async ({ page }) => {
    await open(page)
    const line = lines(page).first()
    const was = (await line.getAttribute('data-out')) === 'true'
    await line.dispatchEvent('click') // a line's box is not the line: click the element, not a point in the box
    await expect(line).toHaveAttribute('data-out', String(!was))
    await line.dispatchEvent('click')
    await expect(line).toHaveAttribute('data-out', String(was))
  })

  test('a change made on one screen shows on another, and Reset grid puts the grid back', async ({ browser }) => {
    const one = await (await browser.newContext()).newPage()
    const other = await (await browser.newContext()).newPage()
    await open(one)
    await open(other)
    const line = lines(one).first()
    const name = await line.getAttribute('data-testid')
    const was = (await line.getAttribute('data-out')) === 'true'
    await line.dispatchEvent('click')
    await expect(other.locator(`[data-testid="${name}"]`)).toHaveAttribute('data-out', String(!was))
    await reset(other)
    await expect(one.locator(`[data-testid="${name}"]`)).toHaveAttribute('data-out', String(was))
  })
})
