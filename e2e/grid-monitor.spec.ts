import { test, expect, type Page } from '@playwright/test'

// The grid monitor shows the live grid: one simulation of the grid in the CIM
// graph, and one alarm list, for every client. Some tests split the grid on the
// CIM graph (which every visitor shares) and put it back afterwards, so they run
// one after the other.
test.describe.configure({ mode: 'serial' })

/** A client id for the commands this spec sends itself (digits, as every id is). */
const SPEC_CLIENT = '990001'

/** The sample grid's two lines into Gamma: out, they split Gamma (with its own
 *  generator) off from Alpha and Beta, which the detector calls an island. */
const GAMMA_LINES = ['Alpha-Gamma 400 kV line', 'Beta-Gamma 400 kV line']

/**
 * Split the grid through the CIM graph app, the graph's one writer, as a visitor
 * on the grid page would. Runs against the three-substation sample grid (CI sets
 * PSWAMP_CIM_PATH to it); on any other grid, or a read-only graph, the test is
 * skipped, since which lines island what is the grid's own business.
 */
async function islandGamma(page: Page) {
    await expect
        .poll(async () => (await page.request.get('/api/cim-graph/layout')).status(), { timeout: 60_000 })
        .toBe(200)
    const layout = await (await page.request.get('/api/cim-graph/layout')).json()
    const lines = GAMMA_LINES.map((name) =>
        layout.branches.find((branch: { name: string }) => branch.name === name),
    )
    test.skip(lines.some((line) => !line), 'needs the sample grid (PSWAMP_CIM_PATH)')
    for (const line of lines) {
        const answer = await page.request.post(`/api/cim-graph/lines/${line.mrid}?client_id=${SPEC_CLIENT}`, {
            data: { open: true },
        })
        test.skip(!answer.ok(), `the graph cannot be edited: ${answer.status()}`)
    }
}

/** Put the grid back as it was loaded. */
async function resetGrid(page: Page) {
    await page.request.post(`/api/cim-graph/reset?client_id=${SPEC_CLIENT}`)
}

const DOCKS = [
    'Grid view',
    'Apps',
    'Frequency',
    'Status',
    'Alarms',
    'Voltage phasors',
    'Line outages',
]

const gridCanvas = (page: Page) =>
    page.getByRole('img', { name: /grid, coloured by detected island/ })

/**
 * What the grid view is showing, as counts of its pixels. What a canvas shows
 * cannot be asked of the DOM, so the pixels are read and sorted:
 *
 * - `lit` is anything that is not background. The plot background is a dark
 *   teal whose red channel is 30; everything drawn over it is far brighter.
 * - `red` and `blue` are what a heat map tints the map, once its quantity is well
 *   off the middle of its scale: red where it is low, blue where it is high.
 *   Nothing else on the view is a red or a blue this pure, apart from the few
 *   pixels of a dead branch.
 *
 * The view is a WebGL canvas, which has no `getImageData` of its own, so it is
 * copied onto a 2D one and read there.
 */
async function countPixels(page: Page): Promise<{ lit: number; red: number; blue: number }> {
    return gridCanvas(page).evaluate((canvas: HTMLCanvasElement) => {
        const copy = document.createElement('canvas')
        copy.width = canvas.width
        copy.height = canvas.height
        const ctx = copy.getContext('2d')!
        ctx.drawImage(canvas, 0, 0)
        const { data } = ctx.getImageData(0, 0, copy.width, copy.height)
        const counts = { lit: 0, red: 0, blue: 0 }
        for (let i = 0; i < data.length; i += 4) {
            const [r, g, b] = [data[i], data[i + 1], data[i + 2]]
            if (r > 90) counts.lit++
            if (r > 90 && g < 60 && b < 70) counts.red++
            if (b > 150 && r < 90 && g < 90) counts.blue++
        }
        return counts
    })
}

const litPixels = async (page: Page) => (await countPixels(page)).lit
const tintedPixels = async (page: Page, tint: 'red' | 'blue') =>
    (await countPixels(page))[tint]

test.describe('Grid monitor', () => {
    test.afterEach(async ({ page }) => resetGrid(page))

    test('opens as a main window: the grid view and its docks', async ({ page }) => {
        await page.goto('/')
        for (const dock of DOCKS) {
            await expect(page.getByRole('region', { name: dock })).toBeVisible()
        }
        // A window, not a document: nothing on it is reached by scrolling the page.
        const overflow = await page.evaluate(
            () => document.documentElement.scrollHeight - window.innerHeight,
        )
        expect(overflow).toBeLessThanOrEqual(0)
    })

    test('opens five sockets, one per stream, however many views read them', async ({ page }) => {
        // Only the monitor's: under the Vite dev server the page also holds a
        // hot-reload socket, and every page holds the error tray's.
        const sockets: string[] = []
        page.on('websocket', (ws) => {
            const { pathname } = new URL(ws.url())
            if (pathname.includes('/api/') && !pathname.endsWith('/api/errors/ws')) sockets.push(pathname)
        })
        await page.goto('/')
        await expect(page.getByRole('region', { name: 'Status' }).getByRole('row', { name: /islanding-detection/ })).toBeVisible({ timeout: 60_000 })
        await expect.poll(() => [...sockets].sort()).toEqual([
            '/api/app-status/ws',
            '/api/islanding/ws',
            '/api/line-outage/ws',
            '/api/phasors/ws',
            '/api/time-window/ws',
        ])
    })

    test('draws the grid, in 3D and in 2D', async ({ page }) => {
        await page.goto('/')
        const view = page.getByRole('region', { name: 'Grid view' })

        await expect(view.getByRole('button', { name: '3d', exact: true })).toHaveAttribute('aria-pressed', 'true')
        await expect.poll(() => litPixels(page)).toBeGreaterThan(1000)

        await view.getByRole('button', { name: '2d', exact: true }).click()
        await expect(view.getByRole('button', { name: '2d', exact: true })).toHaveAttribute('aria-pressed', 'true')
        await expect.poll(() => litPixels(page)).toBeGreaterThan(1000)
    })

    test('a layer can be switched off and on', async ({ page }) => {
        await page.goto('/')
        const view = page.getByRole('region', { name: 'Grid view' })
        await expect.poll(() => litPixels(page)).toBeGreaterThan(1000)
        const everything = await litPixels(page)

        await view.getByRole('button', { name: 'Layers' }).click()
        await view.getByRole('checkbox', { name: 'Lines', exact: true }).uncheck()
        await expect.poll(() => litPixels(page)).toBeLessThan(everything * 0.6)

        await view.getByRole('checkbox', { name: 'Lines', exact: true }).check()
        await expect.poll(() => litPixels(page)).toBeGreaterThan(everything * 0.8)
    })

    test('the voltage heat map can be spread over the grid, flat and as a surface', async ({ page }) => {
        // A healthy grid sits within a few percent of nominal, the middle of the
        // scale, so there is no tint to count: this checks the layer and its scale.
        await page.goto('/')
        const view = page.getByRole('region', { name: 'Grid view' })
        await expect.poll(() => litPixels(page)).toBeGreaterThan(1000)

        await view.getByRole('button', { name: 'Layers' }).click()
        await view.getByRole('radio', { name: 'Voltage heat map' }).check()
        await expect(view.getByLabel(/Colour scale: voltage/)).toBeVisible()
        await view.getByRole('button', { name: '2d', exact: true }).click()
        await expect(view.getByLabel(/Colour scale: voltage/)).toBeVisible()
        await expect.poll(() => litPixels(page)).toBeGreaterThan(1000)

        await view.getByRole('radio', { name: 'No heat map' }).check()
        await expect(view.getByLabel(/Colour scale: voltage/)).toBeHidden()
    })

    test('the frequency heat map colours an island as it splits off', async ({ page }) => {
        // The detector needs its 10 s window after the split, so this waits for real time to pass.
        test.setTimeout(120_000)
        await page.goto('/')
        const view = page.getByRole('region', { name: 'Grid view' })

        await view.getByRole('button', { name: 'Layers' }).click()
        await view.getByRole('radio', { name: 'Frequency heat map' }).check()
        await expect(view.getByLabel(/Colour scale: frequency/)).toBeVisible()

        // Split apart, the two halves run at frequencies far more than the
        // scale's 35 mHz apart, so one is its blue end and the other its red:
        // as a surface in 3D, and as the flat map in 2D.
        await islandGamma(page)
        await expect(view.getByText(/\d+ islands?/)).toBeVisible({ timeout: 90_000 })
        await expect.poll(() => tintedPixels(page, 'blue')).toBeGreaterThan(200)
        await expect.poll(() => tintedPixels(page, 'red')).toBeGreaterThan(200)

        await view.getByRole('button', { name: '2d', exact: true }).click()
        await expect.poll(() => tintedPixels(page, 'blue')).toBeGreaterThan(200)

        await view.getByRole('radio', { name: 'No heat map' }).check()
        await expect.poll(() => tintedPixels(page, 'blue')).toBeLessThan(200)
    })

    test('lists the modules analysing the live grid in the status dock', async ({ page }) => {
        await page.goto('/')
        const status = page.getByRole('region', { name: 'Status' })
        for (const module of ['islanding-detection', 'line-outage']) {
            await expect(status.getByRole('row', { name: new RegExp(module) })).toBeVisible({ timeout: 60_000 })
        }
        await expect(status.getByText(/Live simulation \(rtsim\)/)).toBeVisible()
    })

    test('an islanding alarm opens its details beneath the grid', async ({ page }) => {
        // The detector needs its 10 s window after the split, so this waits for real time to pass.
        test.setTimeout(120_000)
        await page.goto('/')
        await islandGamma(page)

        const alarm = page
            .getByRole('region', { name: 'Alarms' })
            .getByRole('row', { name: /islanding-detection/ })
            .first()
        await expect(alarm).toBeVisible({ timeout: 90_000 })
        // The same event, seen by the grid view: it reports the split.
        await expect(page.getByRole('region', { name: 'Grid view' }).getByText(/\d+ islands?/)).toBeVisible()

        await alarm.click()
        const details = page.getByRole('region', { name: 'Alarm details' })
        await expect(details).toBeVisible()
        await expect(details.getByText('Detected by')).toBeVisible()
        await expect(details.getByRole('cell', { name: 'init', exact: true })).toBeVisible()

        // Operator actions land in the alarm's event log, pushed back down the socket.
        await details.getByRole('button', { name: 'Acknowledge' }).click()
        await expect(details.getByRole('cell', { name: 'acknowledge', exact: true })).toBeVisible()

        await details.getByRole('textbox', { name: 'Annotation' }).fill('seen in e2e')
        await details.getByRole('button', { name: 'Annotate' }).click()
        await expect(details.getByRole('cell', { name: 'seen in e2e' })).toBeVisible()

        await details.getByRole('button', { name: 'Close alarm details' }).click()
        await expect(details).toBeHidden()
    })

    test('the apps dock opens an application\'s own view', async ({ page }) => {
        await page.goto('/')
        await page
            .getByRole('region', { name: 'Apps' })
            .getByRole('link', { name: 'Time window plot' })
            .click()
        await expect(page).toHaveURL(/\/time-window$/)
        await expect(page.getByText('Live Measurements')).toBeVisible()
    })

    for (const [path, title] of [
        ['/islanding', 'Grid view'],
        ['/time-window', 'Live Measurements'],
        ['/phasors', 'Voltage phasors'],
        ['/line-outage', 'Line outages'],
        ['/app-status', 'Status'],
    ]) {
        test(`${path} renders its panel full size`, async ({ page }) => {
            await page.goto(path)
            await expect(page.getByText(title, { exact: true }).first()).toBeVisible()
            // Connected and past the waiting notice: the panel is showing data.
            // A page with two panels shows two notices, hence a count.
            await expect(page.getByText('Waiting for state…')).toHaveCount(0)
            await expect(page.getByText(/Cannot reach the server|Lost connection/)).toBeHidden()
        })
    }
})
