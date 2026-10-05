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
})
