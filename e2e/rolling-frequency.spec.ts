import { test, expect, type Page } from '@playwright/test'

import { choose } from './helpers'

/**
 * Rolling frequency: a module with a five-second window over a 30 s recording.
 * It answers nothing while its window fills, which it does again after every
 * seek; the server keeps the results computed for the recording and shows them
 * again at a seek back, for any client.
 *
 * The kept results are the server's, shared by every page: these tests only
 * rely on what holds whatever was played before them. No result can exist for
 * the recording's first five seconds, and one played here is kept.
 */

const cursor = (page: Page) => page.getByTestId('cursor')
const result = (page: Page) => page.getByTestId('result')
const origin = (page: Page) => page.getByTestId('origin')
const filling = (page: Page) => page.getByTestId('filling')
const slider = (page: Page) => page.getByRole('slider', { name: 'Seek' })

async function open(page: Page) {
  await page.goto('/rolling-frequency')
  await expect(page.getByRole('button', { name: 'Play', exact: true })).toBeEnabled()
  await expect(cursor(page)).toHaveText('t = 0.0 s of 30 s · Paused')
}

/** Play at 5× until the cursor is at least 8 s in, then pause. Not faster: the
 *  module starts its window over if a frame is lost on the way to it. */
async function playPastEightSeconds(page: Page) {
  await choose(page, 'Speed', '5×')
  await page.getByRole('button', { name: 'Play', exact: true }).click()
  await expect(cursor(page)).toHaveText(/^t = (8|9|[12]\d)\.\d s of 30 s · Playing$/)
  await page.getByRole('button', { name: 'Pause', exact: true }).click()
  await expect(cursor(page)).toHaveText(/ · Paused$/)
}

test.describe('Rolling frequency', () => {
  test('opens paused at the start, with the window still to fill', async ({ page }) => {
    await open(page)
    await expect(filling(page)).toContainText('needs 5 s of unbroken frames')
    await expect(result(page)).toHaveCount(0)
  })

  test('playing past five seconds brings the module\'s own results', async ({ page }) => {
    await open(page)
    await playPastEightSeconds(page)
    await expect(result(page)).toHaveText(/^\d{2}\.\d{4} Hz$/)
    await expect(origin(page)).toHaveText('Computed now')
    await expect(page.getByText('Mean over the last 5 s (51 frames).')).toBeVisible()
  })

  test('seeking back over what has played shows the kept result at once', async ({ page }) => {
    await open(page)
    await playPastEightSeconds(page)
    await slider(page).fill('6')
    await expect(cursor(page)).toHaveText('t = 6.0 s of 30 s · Paused')
    // Paused: one frame reached the module since the seek, so it cannot have answered.
    await expect(origin(page)).toHaveText('From cache')
    await expect(result(page)).toHaveText(/^\d{2}\.\d{4} Hz$/)
  })

  test('where no window can be full there is no result, kept or not', async ({ page }) => {
    await open(page)
    await playPastEightSeconds(page)
    await slider(page).fill('2')
    await expect(cursor(page)).toHaveText('t = 2.0 s of 30 s · Paused')
    await expect(filling(page)).toBeVisible()
    await expect(result(page)).toHaveCount(0)
  })

  test('another browser gets the results the first one computed', async ({ browser }) => {
    const [first, second] = await Promise.all([browser.newPage(), browser.newPage()])
    await Promise.all([open(first), open(second)])
    await playPastEightSeconds(first)
    await expect(cursor(second)).toHaveText('t = 0.0 s of 30 s · Paused') // its own replay, untouched
    await slider(second).fill('6')
    await expect(cursor(second)).toHaveText('t = 6.0 s of 30 s · Paused')
    await expect(origin(second)).toHaveText('From cache')
    await Promise.all([first.close(), second.close()])
  })
})
