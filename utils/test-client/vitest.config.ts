import { defineConfig } from 'vitest/config';

// Root config exists only to declare the two projects. Their options stay in
// their own files (`vitest.client.config.ts`, `server/vitest.config.ts`):
// projects referenced as config-file paths inherit nothing from here, which is
// exactly the isolation the old `vitest.workspace.ts` gave us.
//
// This replaces that workspace file. Vitest renamed `workspace` to
// `test.projects` in 3.2 -- and 3.2 warns on every run that the workspace file
// "will be removed in the next major". It was: vitest 4 dropped it, and since
// there was no root config to fall back on, vitest 5 silently ran all 19 test
// files under its *default* config -- no `@client` alias, no jsdom, no
// setupFiles -- failing 15 of them at import. See PR #35.
export default defineConfig({
  test: { projects: ['./vitest.client.config.ts', './server/vitest.config.ts'] },
});
