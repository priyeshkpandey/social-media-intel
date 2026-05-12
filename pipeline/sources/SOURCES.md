# Data sources

All sources here are public RSS / open APIs with permissive read access. **No scraping of X (Twitter) or LinkedIn.** When adding a new source, document its ToS/license posture below before merging.

| Source | Endpoint | Auth | ToS posture | Notes |
|---|---|---|---|---|
| Reddit | OAuth: `https://oauth.reddit.com/r/<sub>/new.json`; anon fallback: `https://old.reddit.com/r/<sub>/new.json` | App-only OAuth via `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` env vars (anonymous endpoint is blocked from data-center IPs) | Reddit ended self-service API key creation Nov 2025 ("Responsible Builder Policy") — new credentials need pre-approval via Reddit's Developer Support form | Subreddit list in `pipeline/config.py` (DECIDE-C). Currently inactive until OAuth is granted. |
| Hacker News (stories) | `https://hn.algolia.com/api/v1/search_by_date` with `tags=story` / `ask_hn` | None | Public API, free | Queries in `HN_QUERIES` |
| Hacker News (comments) | Same endpoint with `tags=comment` | None | Same | Pain-keyword queries in `HN_COMMENT_QUERIES`. Added as a Reddit-alternative — comments are where engineers quantify cost and vent. |
| dev.to | `https://dev.to/api/articles` | None | Public REST API | Filter by tag where helpful |
| Lobsters | `https://lobste.rs/rss` | None | Public RSS | Smaller volume but high-signal |
| Stack Exchange | `https://api.stackexchange.com/2.3/questions` | None for low volume | Free tier: 10k req/day unauth | Filter by site `stackoverflow` + relevant tags |
| Lemmy | `https://<instance>/api/v3/post/list` | None | Public REST API per Lemmy instance | Federated Reddit-clone. Communities in `LEMMY_COMMUNITIES`. Lower volume than Reddit but signal-dense (dev-focused instances). |

## Excluded sources

| Source | Reason |
|---|---|
| X (Twitter) | Free API too limited; paid tiers start at $200/mo; scraping violates ToS |
| LinkedIn | No public-posts API; scraping is explicitly prohibited |

## Status notes

- **Reddit** ingest is gated on credentials (see above). Until then, dataset weight shifts to HN (now including comments) + Lemmy + dev.to + Lobsters + Stack Exchange.
- HN comments add 1 query × 1 tag = +12 query/tag combinations relative to stories alone; expect 3–10× the HN volume.

## Optional backfill

Hugging Face datasets may be used for one-time seeding of the 12-month window if a permissively-licensed software-industry dataset is identified. Document license here before use.
