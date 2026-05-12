# social-media-intel

A weekly-refreshed dashboard of software-industry pain points, mined from public developer communities (Reddit, Hacker News, dev.to, Lobsters, Stack Exchange) and ranked by monetization opportunity.

- **Live dashboard:** _(GitHub Pages URL — populated after first deploy)_
- **How it works:** [`METHODOLOGY.md`](./METHODOLOGY.md)
- **Build prompt (for Claude):** [`BUILD_PROMPT.md`](./BUILD_PROMPT.md)

## Status

v1 live. Weekly refresh runs Sunday 22:00 UTC and publishes a GitHub Release per ISO week (`vYYYY-WW`). The dashboard at the URL above reads the latest release's `dashboard.json` (bundled into the Pages deploy at deploy time).

## Setup (one-time, by the repository owner)

1. **Enable GitHub Pages** — Settings → Pages → Source: **GitHub Actions**.
2. **Add the Reddit OAuth secrets** — Reddit blocks anonymous requests from GitHub-hosted IPs with 403, so app-only OAuth is required for Reddit ingestion.
   - Sign in to Reddit → https://www.reddit.com/prefs/apps → "create another app" → type: **script** → fill the form (redirect URI can be `http://localhost`).
   - Copy the **client ID** (under the app name) and **client secret**.
   - In this repo, Settings → Secrets and variables → Actions → add:
     - `REDDIT_CLIENT_ID`
     - `REDDIT_CLIENT_SECRET`
   - Without these the pipeline still runs, but every Reddit subreddit fetch will fail with 403 and the dataset will be HN/dev.to/Lobsters/Stack Exchange only.
3. **(Optional) Add the LLM secret** — `ANTHROPIC_API_KEY`. Without it the pipeline runs in heuristic-only mode and the dashboard shows a banner.
4. **Trigger the first refresh manually** — Actions → "Weekly refresh" → Run workflow on `main`. This populates the first GitHub Release and triggers the Pages deploy.
5. **Enable the weekly cron** (after a successful manual run) — edit `.github/workflows/refresh.yml`, uncomment the `schedule:` block, commit and push. See `BUILD_PROMPT.md` §13 Step 14.

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
