# _legacy-ui — pre-redesign UI (archived, not built)

This is the **old launcher UI** that predates the current `src/redesign/` app.
It is **not referenced by the app entry** (`index.html` → `src/main.tsx` →
`src/redesign/App`) and is **not included in any build** (Vite bundles only what
is reachable from the entry; `tsconfig` `include` is `["src"]`).

It was moved here from `src/` on 2026-06-10 to remove ~13k lines of dead code
from the active source tree (it was a maintenance hazard — easy to edit by
mistake). Kept in the repo, with git history intact, in case any piece needs to
be referenced or revived.

If you are sure nothing here is needed, this whole folder can be deleted.

Contents (the former `src/` legacy tree): `App.tsx`, `components/`, `services/`
(incl. the 2.6k-line `phoneApi.ts`), `features/`, `providers/`, `stores/`,
`hooks/`, `theme/`, `types/`, `styles/`, `assets/`.
