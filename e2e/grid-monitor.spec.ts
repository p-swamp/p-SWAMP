import { test, expect, type Page } from '@playwright/test'

// Every test here is a new browser profile, so a new client id, so a new PMU
// pipeline on the server — which runs at most eight at once and reclaims only
// idle ones. One at a time keeps this file from being refused by its own load.
test.describe.configure({ mode: 'serial' })

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
    page.getByRole('img', { name: /Nordic 44 grid/ })

/** How much of the grid view is not background. The view is a canvas, so what
 *  it shows cannot be asked of the DOM; the plot background is a dark teal whose
 *  red channel is 30, and everything drawn over it is far brighter. */
async function litPixels(page: Page): Promise<number> {
    return gridCanvas(page).evaluate((canvas: HTMLCanvasElement) => {
        const { data } = canvas
            .getContext('2d')!
            .getImageData(0, 0, canvas.width, canvas.height)
        let lit = 0
        for (let i = 0; i < data.length; i += 4) if (data[i] > 90) lit++
        return lit
    })
}

test.describe('Grid monitor', () => {

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
        // Only the api's: under the Vite dev server the page also holds a
        // hot-reload socket, which is no part of the app.
        const sockets: string[] = []
        page.on('websocket', (ws) => {
            const { pathname } = new URL(ws.url())
            if (pathname.includes('/api/')) sockets.push(pathname)
        })
        await page.goto('/')
        await expect(page.getByRole('region', { name: 'Status' }).getByRole('row', { name: /Measurement Store/ })).toBeVisible()
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
        await expect.poll(() => litPixels(page)).toBeGreaterThan(5000)

        await view.getByRole('button', { name: '2d', exact: true }).click()
        await expect(view.getByRole('button', { name: '2d', exact: true })).toHaveAttribute('aria-pressed', 'true')
        await expect.poll(() => litPixels(page)).toBeGreaterThan(5000)
    })

    test('a layer can be switched off and on', async ({ page }) => {
        await page.goto('/')
        const view = page.getByRole('region', { name: 'Grid view' })
        await expect.poll(() => litPixels(page)).toBeGreaterThan(5000)
        const everything = await litPixels(page)

        await view.getByRole('button', { name: 'Layers' }).click()
        await view.getByRole('checkbox', { name: 'Lines', exact: true }).uncheck()
        await expect.poll(() => litPixels(page)).toBeLessThan(everything * 0.6)

        await view.getByRole('checkbox', { name: 'Lines', exact: true }).check()
        await expect.poll(() => litPixels(page)).toBeGreaterThan(everything * 0.8)
    })

    test('lists the monitoring applications in the status dock', async ({ page }) => {
        await page.goto('/')
        const status = page.getByRole('region', { name: 'Status' })
        for (const app of ['IslandingApp', 'LineOutageDetectionApp', 'Measurement Store']) {
            await expect(status.getByRole('row', { name: new RegExp(app) })).toBeVisible()
        }
        await expect(status.getByText(/PMU replay/)).toBeVisible()
    })

    test('an islanding alarm opens its details beneath the grid', async ({ page }) => {
        // The recorded lines trip twenty seconds into the replay and the detector
        // needs a few more to call it, so this waits for real time to pass.
        test.setTimeout(120_000)
        await page.goto('/')

        const alarm = page
            .getByRole('region', { name: 'Alarms' })
            .getByRole('row', { name: /IslandingApp/ })
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
            await expect(page.getByText('Waiting for state…')).toBeHidden()
            await expect(page.getByText(/Cannot reach the server|Lost connection/)).toBeHidden()
        })
    }
})
