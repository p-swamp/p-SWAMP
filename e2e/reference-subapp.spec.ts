import { test, expect } from '@playwright/test'

test.describe('Reference example', () => {

    test('connects and starts at zero', async ({ page }) => {
        await page.goto('/reference-subapp')
        await expect(page.getByText('Online')).toBeVisible()
        await expect(page.getByRole('status', { name: 'Bump count' })).toHaveText('0')
    })

    test('a trailing slash lands on the same page', async ({ page }) => {
        // Served at /reference-subapp/ the shell cannot find its assets and
        // renders blank; the server redirects to the bare route.
        await page.goto('/reference-subapp/')
        await expect(page).toHaveURL(/\/reference-subapp$/)
        await expect(page.getByRole('status', { name: 'Bump count' })).toHaveText('0')
    })

    test('bump increments, reset returns to zero', async ({ page }) => {
        await page.goto('/reference-subapp')

        const count = page.getByRole('status', { name: 'Bump count' })
        const bump = page.getByRole('button', { name: 'Bump' })
        const reset = page.getByRole('button', { name: 'Reset' })

        await expect(count).toHaveText('0')

        await bump.click()
        await expect(count).toHaveText('1')

        await bump.click()
        await expect(count).toHaveText('2')
        
        await bump.click()
        await expect(count).toHaveText('3')
        
        await reset.click()
        await expect(count).toHaveText('0')

    })

    test('?client_id= makes a tab a client of its own, through a navigation', async ({ context }) => {
        // The tabs of one context share localStorage, as private windows do.
        // Fresh ids per run: the server keeps a counter per id for its lifetime.
        const a = String(Date.now())
        const b = String(Date.now() + 1)
        const one = await context.newPage()
        const two = await context.newPage()
        await one.goto(`/reference-subapp?client_id=${a}`)
        await two.goto(`/reference-subapp?client_id=${b}`)
        await expect(one.locator('footer')).toContainText(`client id: ${a}`)
        await expect(two.locator('footer')).toContainText(`client id: ${b}`)

        await one.getByRole('button', { name: 'Bump' }).click()
        await one.getByRole('button', { name: 'Bump' }).click()
        await expect(one.getByRole('status', { name: 'Bump count' })).toHaveText('2')
        await expect(two.getByRole('status', { name: 'Bump count' })).toHaveText('0')

        // A navigation drops the query; the tab keeps its id.
        await one.getByRole('link', { name: 'PMU Test Streamer' }).click()
        await one.getByRole('link', { name: 'Reference example' }).click()
        await expect(one).toHaveURL(/\/reference-subapp$/)
        await expect(one.locator('footer')).toContainText(`client id: ${a}`)
        await expect(one.getByRole('status', { name: 'Bump count' })).toHaveText('2')
    })
})
