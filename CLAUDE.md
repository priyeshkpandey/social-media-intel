# CLAUDE.md — Repo guidance for Claude

This repository builds a software-industry pain-point intelligence dashboard. The authoritative spec is [`BUILD_PROMPT.md`](./BUILD_PROMPT.md) — read it before making changes.

## Key conventions

- **Pipeline language:** Python 3.11+, managed with `uv`.
- **Frontend:** Vite + TypeScript + Apache ECharts. No React/Vue.
- **Data persistence:** GitHub Releases (tag `vYYYY-WW`). Never commit data files >1MB to `main`.
- **LLM use:** Anthropic API only, optional, env-gated by `ANTHROPIC_API_KEY`. Heuristic-only path must always work.
- **No scraping** of X/Twitter or LinkedIn. ToS-clean sources only — see `pipeline/sources/SOURCES.md`.

## When making changes

1. Stay within the build plan in `BUILD_PROMPT.md` §13 unless the user says otherwise.
2. One stage / one feature per PR. Small diffs.
3. Update `METHODOLOGY.md` whenever a threshold or rubric in `pipeline/config.py` changes.
4. Decisions marked **DECIDE** in `BUILD_PROMPT.md` require asking the user — never silently pick.

## What lives where

| Concern | Location |
|---|---|
| Source ingesters | `pipeline/sources/` |
| Pipeline stages | `pipeline/stages/` |
| Scoring rubrics | `pipeline/config.py` + `pipeline/stages/score.py` |
| LLM prompts | `pipeline/prompts/*.md` |
| Dashboard rendering | `site/src/render/` |
| Workflows | `.github/workflows/` |
