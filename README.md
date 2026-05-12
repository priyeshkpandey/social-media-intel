# social-media-intel

A weekly-refreshed dashboard of software-industry pain points, mined from public developer communities (Reddit, Hacker News, dev.to, Lobsters, Stack Exchange) and ranked by monetization opportunity.

- **Live dashboard:** _(GitHub Pages URL — populated after first deploy)_
- **How it works:** [`METHODOLOGY.md`](./METHODOLOGY.md)
- **Build prompt (for Claude):** [`BUILD_PROMPT.md`](./BUILD_PROMPT.md)

## Status

Pipeline + dashboard scaffolding are complete; the first real run is gated behind manual workflow dispatch (see Setup below).

## Setup (one-time, by the repository owner)

1. **Enable GitHub Pages** — Settings → Pages → Source: **GitHub Actions**.
2. **(Optional) Add the LLM secret** — Settings → Secrets and variables → Actions → New repository secret named `ANTHROPIC_API_KEY`. Without it the pipeline runs in heuristic-only mode and the dashboard shows a banner.
3. **Trigger the first refresh manually** — Actions → "Weekly refresh" → Run workflow on `main`. This populates the first GitHub Release and triggers the Pages deploy.
4. **Enable the weekly cron** (after a successful manual run) — edit `.github/workflows/refresh.yml`, uncomment the `schedule:` block, commit and push. See `BUILD_PROMPT.md` §13 Step 14.

## Local development

```sh
make sync          # uv sync — install Python deps
make refresh       # run the full pipeline → writes ./out/
make site-dev      # Vite dev server on http://localhost:5173 (serves a bundled sample-dashboard.json)
make site-build    # production build → site/dist/
make test          # pytest
make lint          # ruff + pyright + tsc
```

The site's dev mode reads from `site/public/sample-dashboard.json`; the production build fetches the latest GitHub Release's `dashboard.json` at runtime and caches it in `localStorage`.

## License

MIT
