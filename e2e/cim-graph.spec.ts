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

/** Operate a line from its panel: click it (on the element: a line's box is not the line), then its
 *  panel's button. */
async function operateLine(page: Page, line: Locator) {
  await line.dispatchEvent('click')
  const panel = page.getByTestId('detail-panel')
  await panel.getByRole('button', { name: /^(Take out of service|Bring back into service)$/ }).click()
}

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

  test('clicking a line selects it, and its panel takes it out of service and brings it back', async ({ page }) => {
    await open(page)
    const line = lines(page).first()
    const was = (await line.getAttribute('data-out')) === 'true'
    await line.dispatchEvent('click')
    await expect(line).toHaveAttribute('data-selected', 'true')
    await expect(line).toHaveAttribute('data-out', String(was)) // a click selects, it does not operate
    const panel = page.getByTestId('detail-panel')
    await expect(panel.getByTestId('detail-live')).toContainText(/\d+ A/) // its current, end by end
    await operateLine(page, line)
    await expect(line).toHaveAttribute('data-out', String(!was))
    await operateLine(page, line)
    await expect(line).toHaveAttribute('data-out', String(was))
    await panel.getByRole('button', { name: 'Close' }).click()
    await expect(panel).toBeHidden()
  })

  test('a transformer has its symbol, and its panel takes it out of service and brings it back', async ({ page }) => {
    await open(page)
    const transformer = page.locator('[data-testid^="transformer-"]').first()
    test.skip((await transformer.count()) === 0, 'the grid has no transformer on its layout')
    const was = (await transformer.getAttribute('data-out')) === 'true'
    await transformer.dispatchEvent('click')
    await expect(transformer).toHaveAttribute('data-selected', 'true')
    const panel = page.getByTestId('detail-panel')
    await expect(panel).toContainText('transformer')
    const operate = panel.getByRole('button', { name: /^(Take out of service|Bring back into service)$/ })
    await operate.click()
    await expect(transformer).toHaveAttribute('data-out', String(!was)) // the simulation took it, the graph has it
    await operate.click()
    await expect(transformer).toHaveAttribute('data-out', String(was))
  })

  test('a substation\'s panel shows its stations and the machines and loads at it, live', async ({ page }) => {
    await open(page)
    await page.locator('[data-testid^="substation-"]').first().dispatchEvent('click')
    const live = page.getByTestId('detail-panel').getByTestId('detail-live')
    await expect(live).toContainText(/\d\.\d{4} p\.u\. · \d+\.\d{4} Hz/)
  })

  test('a load\'s panel shows what it draws, as SCADA last scanned it', async ({ page }) => {
    await open(page)
    const load = page.locator('[data-testid^="load-"]').first()
    test.skip((await load.count()) === 0, 'the grid has no loads on its layout')
    await load.dispatchEvent('click')
    const scada = page.getByTestId('detail-panel').getByTestId('detail-scada')
    await expect(scada).toContainText(/Drawing\s*-?\d+\.\d MW · -?\d+\.\d Mvar/) // its P and Q, signed into it
    await expect(scada).toContainText(/Scanned at\s*\d/) // a scan every couple of seconds
  })

  test('a line\'s panel shows its ends\' power flows as SCADA last scanned them', async ({ page }) => {
    await open(page)
    await lines(page).first().dispatchEvent('click')
    const scada = page.getByTestId('detail-panel').getByTestId('detail-scada')
    await expect(scada).toContainText(/End 1 .*-?\d+\.\d MW · -?\d+\.\d Mvar/)
    await expect(scada).toContainText(/End 2 /)
    await expect(scada).toContainText(/Scanned at\s*\d/)
  })

  test('a substation\'s panel shows its voltage and its breakers as SCADA last scanned them', async ({ page }) => {
    await open(page)
    await page.locator('[data-testid^="substation-"]').first().dispatchEvent('click')
    await expect(page.getByTestId('detail-panel').getByTestId('detail-scada')).toContainText(/Voltage, .*\d+\.\d kV/)
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

  test('the status bar sums the generation and the load SCADA last scanned', async ({ page }) => {
    await open(page)
    await expect(page.getByTestId('system-totals')).toHaveText(/^Generation \d+ MW · load \d+ MW \(SCADA, .+\)$/)
  })

  test('a line with a current limit shows its loading on the map', async ({ page }) => {
    await open(page)
    type Feed = { layout: { line_ends: { limit_a: number | null }[] } }
    const limited = await page.evaluate(
      () =>
        new Promise<boolean>((resolve) => {
          const url = `${location.origin.replace(/^http/, 'ws')}/api/cim-live/ws?client_id=1`
          const socket = new WebSocket(url)
          socket.onmessage = (m) => {
            socket.close()
            resolve((JSON.parse(m.data) as Feed).layout.line_ends.some((e) => e.limit_a !== null))
          }
        }),
    )
    test.skip(!limited, 'the grid has no current limits (the sample grid has none)')
    await expect(page.locator('[data-testid^="line-"][data-loading]:not([data-loading=""])').first()).toBeAttached()
  })

  test('a line pushed over its limit is tripped by its protection, which the map then shows', async ({ page }) => {
    // Nordic44 by name: tripping Aurland-Eidfjord puts Aurland-Geilo at 1.2 x its limit, which its
    // inverse-time relay trips in about 25 s. Elsewhere (the sample grid has no limits) it skips.
    test.slow()
    await open(page)
    type Layout = { branches: { name: string }[] }
    const layout = (await (await page.request.get('/api/cim-graph/layout')).json()) as Layout
    test.skip(!layout.branches.some((b) => b.name === '420AURLAND-EIDFJORD'), 'needs Nordic44')
    const tripped = page.locator('[data-testid="line-420AURLAND-EIDFJORD"]')
    await rightClick(tripped)
    await page.getByTestId('disturbance-menu').getByRole('menuitem', { name: 'Trip' }).click()
    // The log keeps earlier events (a reset's, an earlier run's protection): first this trip, then what
    // protection does about it, written to the graph, on the map. A cascade follows (Aurland-Hagafoss).
    const log = page.getByTestId('event-log')
    await expect(log.locator('li').first()).toHaveAttribute('data-cause', 'disturbance')
    await expect(page.locator('[data-testid="line-420AURLAND-GEILO"]')).toHaveAttribute('data-out', 'true', { timeout: 90_000 })
    await expect(log.locator('li[data-cause="protection"][data-kind="trip"]', { hasText: '420AURLAND-GEILO' }).first()).toBeVisible()
    await expect(tripped).toHaveAttribute('data-out', 'false') // the disturbance never reaches the graph
    await reset(page)
  })

  test('a change made on one screen shows on another, and Reset grid puts the grid back', async ({ browser }) => {
    const one = await (await browser.newContext()).newPage()
    const other = await (await browser.newContext()).newPage()
    await open(one)
    await open(other)
    const line = lines(one).first()
    const name = await line.getAttribute('data-testid')
    const was = (await line.getAttribute('data-out')) === 'true'
    await operateLine(one, line)
    await expect(other.locator(`[data-testid="${name}"]`)).toHaveAttribute('data-out', String(!was))
    await reset(other)
    await expect(one.locator(`[data-testid="${name}"]`)).toHaveAttribute('data-out', String(was))
  })
})
