import { test, expect, type Page } from '@playwright/test'

import { choose, compose, underCompose } from './helpers'

/**
 * The PMU test streamer: every part of the server data architecture, through
 * the page. Runs against compose (Kafka, workers, the remote data stub), a bare
 * `docker run` (in-memory, no remote source) or minikube (E2E_BASE_URL).
 */

const frame = (page: Page) => page.getByTestId('frame-readout')
const source = (page: Page) => page.getByRole('group', { name: 'Source' })

/** The sample recording's frame `n` (1-based) as the readout spells it: 60
 *  frames at 20 Hz from 2026-01-01 00:00:00.050 UTC. */
function sampleFrame(n: number): string {
  const ms = 50 * n
  return `2026-01-01 00:00:${String(Math.floor(ms / 1000)).padStart(2, '0')}.${String(ms % 1000).padStart(3, '0')} UTC`
}

async function open(page: Page) {
  await page.goto('/pmu-test-streamer')
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeEnabled()
  await expect(frame(page)).toHaveText(sampleFrame(1))
}

async function switchTo(page: Page, name: string) {
  await source(page).getByRole('button', { name, exact: true }).click()
  await expect(source(page).getByRole('button', { name, exact: true })).toHaveAttribute('aria-pressed', 'true')
}

test.describe('PMU test streamer', () => {
  test('opens paused on the recording, with the CIM reference and module results', async ({ page }) => {
    await open(page)
    await expect(page.getByText(/^Recorded · Paused$/)).toBeVisible()
    await expect(page.getByRole('row')).toHaveCount(6) // five stations
    await expect(page.getByText(/^CIM reference: (?!none$)\S+$/)).toBeVisible() // the grid in the CIM graph
    await expect(page.getByTestId('stats-readout')).toHaveText(/^mean f \d+\.\d{4} Hz · .* · 5 stations$/)
    await expect(page.getByTestId('excursion-readout')).toContainText('in band')
  })

  test('play and pause', async ({ page }) => {
    await open(page)
    await page.getByRole('button', { name: 'Play', exact: true }).click()
    await expect(page.getByText(/^Recorded · Playing$/)).toBeVisible()
    await expect(frame(page)).not.toHaveText(sampleFrame(1))
    await page.getByRole('button', { name: 'Pause', exact: true }).click()
    await expect(page.getByText(/^Recorded · Paused$/)).toBeVisible()
  })

  test('step forward and back, and seek', async ({ page }) => {
    await open(page)
    const forward = page.getByRole('button', { name: 'Step forward', exact: true })
    await forward.click()
    await forward.click()
    await expect(frame(page)).toHaveText(sampleFrame(3))
    await page.getByRole('button', { name: 'Step back', exact: true }).click()
    await expect(frame(page)).toHaveText(sampleFrame(2))
    await page.getByRole('slider', { name: 'Seek' }).fill('1.5')
    await expect(frame(page)).toHaveText(sampleFrame(31)) // 1.5 s after the first frame
  })

  test('speed is the player\'s, and survives a reload', async ({ page }) => {
    await open(page)
    await choose(page, 'Speed', '2×')
    await page.reload()
    await expect(page.getByRole('combobox', { name: 'Speed' })).toHaveText('2×')
  })

  test('a chunk plays and stops at its end', async ({ page }) => {
    await open(page)
    await page.getByRole('button', { name: 'Play next 1 s', exact: true }).click()
    await expect(page.getByText(/^Recorded · Ended$/)).toBeVisible({ timeout: 5000 })
    await expect(frame(page)).toHaveText(sampleFrame(20)) // the last frame before one second on
  })

  test('the excursion module pauses the player at the trip', async ({ page }) => {
    await open(page)
    // Its checked state is the module's (the page renders it from the result), so click and wait.
    await page.getByRole('checkbox', { name: 'Pause on excursion' }).click()
    await expect(page.getByRole('checkbox', { name: 'Pause on excursion' })).toBeChecked()
    await choose(page, 'Speed', '2×')
    await page.getByRole('button', { name: 'Play', exact: true }).click()
    await expect(page.getByText(/^Recorded · Playing$/)).toBeVisible()
    await expect(page.getByText(/^Recorded · Paused$/)).toBeVisible({ timeout: 5000 })
    await expect(page.getByTestId('excursion-readout')).toContainText('out of band')
    await expect(page.getByTestId('excursion-readout')).toContainText('1 so far')
  })

  test('a range summary, and a refused one on the error tray', async ({ page }) => {
    await open(page)
    await page.getByRole('button', { name: 'Summarize next 1 s', exact: true }).click()
    await expect(page.getByTestId('summary-readout')).toContainText(`sample · ${sampleFrame(1)} + 1.00 s · 20 frames`)
    await switchTo(page, 'live')
    await page.getByRole('button', { name: 'Summarize next 1 s', exact: true }).click()
    const tray = page.getByRole('region', { name: 'Errors' })
    await expect(tray).toContainText('range-summary refused summarize.range')
    await expect(tray).toContainText('live is live')
  })

  test('live is followed with no transport controls, and back', async ({ page }) => {
    await open(page)
    await switchTo(page, 'live')
    await expect(page.getByText('LIVE', { exact: true })).toBeVisible()
    await expect(frame(page)).toHaveText(/^Live · /)
    await expect(page.getByTestId('stats-readout')).toHaveText(/^mean f /)
    for (const name of ['Play', 'Pause', 'Step forward', 'Step back']) {
      await expect(page.getByRole('button', { name, exact: true })).toBeDisabled()
    }
    await expect(page.getByRole('slider', { name: 'Seek' })).toBeDisabled()
    // The excursion module reads the shared stream: no per-viewer setting (a 409 server-side).
    await expect(page.getByRole('checkbox', { name: 'Pause on excursion' })).toBeDisabled()
    await switchTo(page, 'sample')
    await expect(page.getByText(/^Recorded · Paused$/)).toBeVisible()
    await expect(frame(page)).toHaveText(sampleFrame(1))
  })

  test('two browsers on live see the same frames; on the recording, their own', async ({ browser }) => {
    const [a, b] = await Promise.all([browser.newPage(), browser.newPage()])
    await Promise.all([open(a), open(b)])
    await a.getByRole('button', { name: 'Step forward', exact: true }).click()
    await a.getByRole('button', { name: 'Step forward', exact: true }).click()
    await expect(frame(a)).toHaveText(sampleFrame(3))
    await expect(frame(b)).toHaveText(sampleFrame(1)) // separate replays
    await Promise.all([switchTo(a, 'live'), switchTo(b, 'live')])
    const seen = { a: new Set<string>(), b: new Set<string>() }
    for (let i = 0; i < 40; i++) {
      seen.a.add(await frame(a).innerText())
      seen.b.add(await frame(b).innerText())
    }
    const shared = [...seen.a].filter((text) => text.startsWith('Live') && seen.b.has(text))
    expect(shared.length).toBeGreaterThan(0) // one shared live run, stamped once
    await Promise.all([a.close(), b.close()])
  })

  // Both read the remote data stub, and the second stops it: one after the other,
  // or the second takes the stub away from the first part way.
  test.describe('the remote source', () => {
    test.describe.configure({ mode: 'serial' })

    test('a year of history, moved around on the timeline', async ({ page }) => {
      // The remote data stub serves synthetic-history: a year from 2025-10-01 at
      // 20 Hz, with a 2.5 s dropout ten seconds in and three days missing from
      // 2026-01-10 (modules/synthetic-history/).
      await open(page)
      test.skip((await source(page).getByRole('button', { name: 'remote', exact: true }).count()) === 0, 'no remote source configured')
      await switchTo(page, 'remote')
      await expect(page.getByTestId('coverage-readout')).toHaveText(
        'Coverage 2025-10-01 00:00:00 → 2026-10-01 00:00:00 UTC · 365 d',
      )
      await expect(frame(page)).toHaveText('2025-10-01 00:00:00.000 UTC')
      const tray = page.getByRole('region', { name: 'Errors' })
      const jump = async (to: string) => {
        await page.getByLabel('Jump to (UTC)').fill(to)
        await page.getByRole('button', { name: 'Go', exact: true }).click()
      }

      // Into the 3-day outage: it lands on the first frame after it, and says so.
      await jump('2026-01-11 00:00')
      await expect(frame(page)).toHaveText('2026-01-13 00:00:00.000 UTC')
      await expect(tray).toContainText('no data from remote for 2 d')

      // A nudge, then the slider over a one-minute view, centred on the cursor.
      await page.getByRole('button', { name: 'Forward 1 h', exact: true }).click()
      await expect(frame(page)).toHaveText('2026-01-13 01:00:00.000 UTC')
      await choose(page, 'View span', '1 min')
      await page.getByRole('slider', { name: 'Seek' }).fill('45') // the view is [00:59:30, 01:00:30)
      await expect(frame(page)).toHaveText('2026-01-13 01:00:15.000 UTC')

      // Playing across the dropout crosses it at once and reports it.
      await jump('2025-10-01 00:00:09.500')
      await expect(frame(page)).toHaveText('2025-10-01 00:00:09.500 UTC')
      await page.getByRole('button', { name: 'Play', exact: true }).click()
      await expect(tray).toContainText('no data from remote for 2.50 s', { timeout: 5000 })
      await expect(page.getByTestId('stats-readout')).toHaveText(/^mean f /)
    })

    test('a provider that goes away stops the stream and says so', async ({ page }) => {
      test.skip(!underCompose('remote-data-stub'), 'needs the compose stack as the server under test')
      await open(page)
      test.skip((await source(page).getByRole('button', { name: 'remote', exact: true }).count()) === 0, 'no remote source configured')
      await switchTo(page, 'remote')
      compose('stop remote-data-stub')
      try {
        await page.getByRole('slider', { name: 'Seek' }).fill('1')
        await expect(page.getByRole('region', { name: 'Errors' })).toContainText('the stream from remote stopped')
        await expect(page.getByText(/remote: ConnectionError/).first()).toBeVisible()
      } finally {
        compose('start remote-data-stub')
      }
    })
  })
})
