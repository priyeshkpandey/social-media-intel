// Dashboard data loading.
//
// Dev mode  → fetch `/sample-dashboard.json` (served from `public/`).
// Prod mode → fetch `./dashboard.json`, a same-origin asset bundled into the
//             Pages deploy artifact by `.github/workflows/deploy.yml`. The
//             workflow downloads the latest GitHub Release's dashboard.json
//             at deploy time and copies it into `site/dist/`, so the browser
//             never has to make a CORS request to release-asset URLs (which
//             don't send `Access-Control-Allow-Origin`).

const STALE_AFTER_DAYS = 10;

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
  const url = import.meta.env.DEV ? "/sample-dashboard.json" : "./dashboard.json";
  const data = await fetchJson<Dashboard>(url);
  const stale = isStale(data.generated_at, STALE_AFTER_DAYS);
  return {
    data,
    stale,
    published_at: data.generated_at,
    source: import.meta.env.DEV ? "local" : "release",
  };
}

async function fetchJson<T>(url: string): Promise<T> {
  const resp = await fetch(url);
  if (!resp.ok) {
    throw new Error(`${resp.status} ${resp.statusText} fetching ${url}`);
  }
  return (await resp.json()) as T;
}

function isStale(generatedAt: string, maxAgeDays: number): boolean {
  const ageMs = Date.now() - new Date(generatedAt).getTime();
  return ageMs > maxAgeDays * 24 * 60 * 60 * 1000;
}
