import { execSync } from 'node:child_process'
import path from 'node:path'

import { expect, type Page } from '@playwright/test'

const REPO_ROOT = path.resolve(__dirname, '..')

/** The compose services running now; empty when the server under test is
 *  something else (a bare `docker run`, minikube). */
export function composeServices(): string[] {
  try {
    const out = execSync('docker compose ps --services --status running', {
      cwd: REPO_ROOT,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
    return out.toString().split('\n').map((s) => s.trim()).filter(Boolean)
  } catch {
    return []
  }
}

/** Whether the server under test is the compose stack's (on :8000), so a
 *  spec may stop and start its services. */
export function underCompose(service: string): boolean {
  const base = process.env.E2E_BASE_URL
  const composeServer = !base || /\/\/(127\.0\.0\.1|localhost):8000\/?$/.test(base)
  return composeServer && composeServices().includes(service)
}

export function compose(args: string): void {
  execSync(`docker compose ${args}`, { cwd: REPO_ROOT, stdio: 'ignore' })
}

/** Pick `option` from the shadcn select labelled `label`. */
export async function choose(page: Page, label: string, option: string): Promise<void> {
  await page.getByRole('combobox', { name: label }).click()
  await page.getByRole('option', { name: option, exact: true }).click()
  await expect(page.getByRole('combobox', { name: label })).toHaveText(option)
}
