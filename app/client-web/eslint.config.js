import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  // `dist` is the build output. `src/api/schema.ts` is generated from
  // doc/api/openapi.json by uv run pswamp api generate — it is checked by
  // `tsc` like everything else, but linting a machine-written file only ever
  // produces noise nobody may fix by hand. Regenerate it, don't edit it.
  globalIgnores(['dist', 'src/api/schema.ts']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
  },
  {
    // Vendored shadcn/ui components: they export style variants (buttonVariants,
    // badgeVariants) alongside the component, which trips the fast-refresh
    // single-export rule. They're generated, not hand-edited, so exempt them.
    files: ['src/components/ui/**'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
])
