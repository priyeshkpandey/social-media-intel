// Dashboard data loading.
//
// Dev mode  → fetch `/sample-dashboard.json` (served from `public/`).
// Prod mode → fetch the latest GitHub Release's `dashboard.json` asset and
//             cache it in `localStorage` keyed by the release `tag_name`.

const REPO = "priyeshkpandey/social-media-intel";
const STALE_AFTER_DAYS = 10;
const CACHE_KEY = "smi:dashboard:v1";

// ---------- types (mirror pipeline/stages/export.py) ----------

export type Feasibility = "low" | "medium" | "high";
export type ImplCostBand = "<$10k" | "$10-100k" | "$100k-1M" | ">$1M";

export interface CostSummary {
  money_median_usd: number | null;
  time_median_days: number | null;
  team_median_people: number | null;
  sample_count: number;
  summary: string;
}

export interface Synthesis {
  title: string;
  one_line_pain: string;
  role_demographics: string;
  perceived_cost_summary: string;
  feasibility: Feasibility;
  implementation_cost_band: ImplCostBand;
  opportunity_pitch: string;
  confidence: number;
}

export interface Post {
  id: string;
  source: string;
  role: string | null;
  url: string;
  score: number;
  replies_count: number;
  text: string;
  posted_at: string;
  sentiment: number;
}

export interface Cluster {
  id: string;
  label: string;
  title: string;
  frequency_per_week: number;
  frequency_zscore: number;
  opportunity: number;
  feasibility: Feasibility;
  impl_cost_band: ImplCostBand;
  cost: CostSummary;
  role_top: Array<{ role: string; share: number }>;
  first_seen: string;
  last_seen: string;
  post_count: number;
  synthesis: Synthesis | null;
  representative_posts: Post[];
}

export interface Opportunity {
  rank: number;
  title: string;
  pain: string;
  pitch: string;
  why_now: string;
  target_role: string;
  evidence_cluster_ids: string[];
  estimated_band: ImplCostBand;
}

export interface Narrative {
  headline: string;
  top_10: Opportunity[];
  honorable_mentions: string[];
}

export interface KpiBlock {
  total_posts_this_week: number;
  active_clusters: number;
  new_clusters_this_week: number;
  mean_opportunity: number;
}

export interface Dashboard {
  schema_version: number;
  generated_at: string;
  run_id: string;
  heuristic_only: boolean;
  kpi: KpiBlock;
  narrative: Narrative | null;
  clusters: Cluster[];
}

export interface LoadResult {
  data: Dashboard;
  stale: boolean;
  published_at: string | null;
  source: "release" | "local";
}

// ---------- loader ----------

export async function loadDashboard(): Promise<LoadResult> {
  if (import.meta.env.DEV) {
    const data = await fetchJson<Dashboard>("/sample-dashboard.json");
    return { data, stale: false, published_at: null, source: "local" };
  }
  return loadFromLatestRelease();
}

interface ReleaseAsset {
  name: string;
  browser_download_url: string;
}

interface ReleaseMeta {
  tag_name: string;
  published_at: string;
  assets: ReleaseAsset[];
}

async function loadFromLatestRelease(): Promise<LoadResult> {
  const release = await fetchJson<ReleaseMeta>(
    `https://api.github.com/repos/${REPO}/releases/latest`,
  );
  const asset = release.assets.find((a) => a.name === "dashboard.json");
  if (!asset) {
    throw new Error(`release ${release.tag_name} has no dashboard.json asset`);
  }

  const stale = isStale(release.published_at, STALE_AFTER_DAYS);
  const cached = readCache(release.tag_name);
  if (cached) {
    return { data: cached, stale, published_at: release.published_at, source: "release" };
  }

  const data = await fetchJson<Dashboard>(asset.browser_download_url);
  writeCache(release.tag_name, data);
  return { data, stale, published_at: release.published_at, source: "release" };
}

// ---------- helpers ----------

async function fetchJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText} fetching ${url}`);
  }
  return (await resp.json()) as T;
}

function isStale(publishedAt: string, maxAgeDays: number): boolean {
  const ageMs = Date.now() - new Date(publishedAt).getTime();
  return ageMs > maxAgeDays * 24 * 60 * 60 * 1000;
}

interface CacheEntry {
  tag: string;
  data: Dashboard;
}

function readCache(tag: string): Dashboard | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const entry = JSON.parse(raw) as CacheEntry;
    return entry.tag === tag ? entry.data : null;
  } catch {
    return null;
  }
}

function writeCache(tag: string, data: Dashboard): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify({ tag, data }));
  } catch {
    // localStorage may be unavailable (privacy mode / quota); non-fatal.
  }
}
