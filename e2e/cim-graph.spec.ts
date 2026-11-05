import { test, expect, type Locator, type Page } from '@playwright/test'

/**
 * The grid page: the grid of the CIM graph on its geographic layout (Leaflet), with a breaker and a
 * line to click, and the live simulation's frequency and voltage, every frame, plotted. The
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

/** Right-click an element of the map, on the element itself: a line's box is not the line, and a
 *  bare `dispatchEvent('contextmenu')` carries no coordinates, which Leaflet cannot place. */
async function rightClick(target: Locator) {
  await target.evaluate((element) => {
    const box = element.getBoundingClientRect()
    const at = { clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 }
    element.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2, ...at }))
  })
}

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
    await expect(breakers(page).first()).toHaveAttribute('title', /\(breaker, /)
    await expect(lines(page).first().locator('title')).toContainText(/service/)
  })

  test('plots every frame of the live simulation, about 50 a second', async ({ page }) => {
    // The first frames can take a while on a fresh stack (the simulation's controller is a process of
    // its own, over Oxigraph): the waits below allow for it, and so must the test's own budget.
    test.slow()
    await page.goto('/cim-graph')
    for (const quantity of ['f', 'v']) {
      await expect(page.getByTestId(`chart-${quantity}`).locator('canvas')).toBeVisible({ timeout: 60_000 })
    }
    await expect(page.getByRole('group', { name: 'Stations' }).getByRole('button').first()).toBeVisible()
    // the page's own count of what reached it over the last 2 s
    await expect
      .poll(
        async () => Number((await page.getByTestId('samples-per-second').textContent())?.match(/(\d+) samples\/s/)?.[1] ?? 0),
        { timeout: 60_000 },
      )
      .toBeGreaterThanOrEqual(40)
  })

  test('picking a station highlights it', async ({ page }) => {
    await page.goto('/cim-graph')
    const station = page.getByRole('group', { name: 'Stations' }).getByRole('button').first()
    await expect(station).toBeVisible({ timeout: 60_000 })
    await station.click()
    await expect(station).toHaveAttribute('aria-pressed', 'true')
    await station.click()
    await expect(station).toHaveAttribute('aria-pressed', 'false')
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

  test('a line tripped from its menu is announced, and the map, which shows the graph, does not change', async ({ page }) => {
    await open(page)
    const line = lines(page).first()
    const was = await line.getAttribute('data-out')
    await rightClick(line)
    const menu = page.getByTestId('disturbance-menu')
    await menu.getByRole('menuitem', { name: 'Trip' }).click()
    await expect(menu).toBeHidden()
    const newest = page.getByTestId('event-log').locator('li').first()
    await expect(newest).toHaveAttribute('data-kind', 'trip')
    await expect(newest).toHaveAttribute('data-cause', 'disturbance')
    await expect(line).toHaveAttribute('data-out', was ?? 'false') // a disturbance never reaches the graph
    await rightClick(line)
    await page.getByTestId('disturbance-menu').getByRole('menuitem', { name: 'Reconnect' }).click()
    await expect(newest).toHaveAttribute('data-kind', 'reconnect')
  })

  test('a fault on a line is cleared by its protection, which opens its breaker on the map', async ({ page }) => {
    await open(page)
    type Layout = { branches: { name: string; kind: string; breaker: string | null }[]; breakers: { mrid: string; name: string }[] }
    const layout = (await (await page.request.get('/api/cim-graph/layout')).json()) as Layout
    const line = layout.branches.find((b) => b.kind === 'line' && b.breaker !== null)
    test.skip(!line, 'no line with a breaker of its own')
    const breakerName = layout.breakers.find((b) => b.mrid === line!.breaker)!.name
    const breaker = page.locator(`[data-testid="breaker-${breakerName}"]`)
    test.skip((await breaker.getAttribute('data-open')) === 'true', 'its breaker starts open')
    await rightClick(page.locator(`[data-testid="line-${line!.name}"]`))
    await page.getByTestId('disturbance-menu').getByRole('menuitem', { name: /^Fault at end 1/ }).click()
    await expect(breaker).toHaveAttribute('data-open', 'true') // protection's doing, written to the graph
    await expect(page.getByTestId('event-log').locator('li[data-cause="protection"]').first()).toBeVisible()
    await reset(page)
  })

  test('a load step from a load\'s menu is announced', async ({ page }) => {
    await open(page)
    const load = page.locator('[data-testid^="load-"]').first()
    test.skip((await load.count()) === 0, 'the grid has no loads on its layout')
    await rightClick(load)
    await page.getByTestId('disturbance-menu').getByRole('menuitem', { name: /^Step to/ }).first().click()
    await expect(page.getByTestId('event-log').locator('li').first()).toHaveAttribute('data-kind', 'load_step')
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
