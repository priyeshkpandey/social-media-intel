# Data sources

All sources here are public RSS / open APIs with permissive read access. **No scraping of X (Twitter) or LinkedIn.** When adding a new source, document its ToS/license posture below before merging.

| Source | Endpoint | Auth | ToS posture | Notes |
|---|---|---|---|---|
| Reddit | `https://old.reddit.com/r/<sub>/new.json` | None for read | Permitted via public JSON; respect `User-Agent` and rate limits | Subreddit list in `pipeline/config.py` (DECIDE-C) |
| Hacker News | `https://hn.algolia.com/api/v1/search_by_date` | None | Public API, free | Filter by software/dev tags via query |
| dev.to | `https://dev.to/api/articles` | None | Public REST API | Filter by tag where helpful |
| Lobsters | `https://lobste.rs/rss` | None | Public RSS | Smaller volume but high-signal |
| Stack Exchange | `https://api.stackexchange.com/2.3/questions` | None for low volume | Free tier: 10k req/day unauth | Filter by site `stackoverflow` + relevant tags |

## Excluded sources

| Source | Reason |
|---|---|
| X (Twitter) | Free API too limited; paid tiers start at $200/mo; scraping violates ToS |
| LinkedIn | No public-posts API; scraping is explicitly prohibited |

## Optional backfill

Hugging Face datasets may be used for one-time seeding of the 12-month window if a permissively-licensed software-industry dataset is identified. Document license here before use.
