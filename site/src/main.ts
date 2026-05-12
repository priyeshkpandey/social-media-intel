import "@picocss/pico/css/pico.min.css";
import "./styles.css";

import type { Dashboard } from "./data";
import { loadDashboard } from "./data";
import { createDrilldownOpener } from "./render/drilldown";
import { renderHeatmap } from "./render/heatmap";
import { renderHero } from "./render/hero";
import { renderKpi } from "./render/kpi";
import { renderTable } from "./render/table";
import { renderTimeseries } from "./render/timeseries";
import { renderTreemap } from "./render/treemap";

async function main(): Promise<void> {
  const app = document.getElementById("app");
  if (!app) return;
  app.innerHTML = '<p aria-busy="true">Loading dashboard…</p>';

  try {
    const result = await loadDashboard();
    app.innerHTML = "";
    renderHeader(app, result.data, result.stale, result.published_at);
    if (result.data.heuristic_only) renderHeuristicBanner(app);
    renderKpi(app, result.data);
    renderHero(app, result.data);

    const openDrilldown = createDrilldownOpener(result.data);
    renderTreemap(app, result.data, openDrilldown);
    renderTimeseries(app, result.data);
    renderHeatmap(app, result.data);
    renderTable(app, result.data, openDrilldown);

    renderFooter(app, result.data);
  } catch (err) {
    renderError(app, err);
  }
}

function renderHeader(
  root: HTMLElement,
  dashboard: Dashboard,
  stale: boolean,
  publishedAt: string | null,
): void {
  const header = document.createElement("header");
  header.className = "smi-header";

  const h1 = document.createElement("h1");
  h1.textContent = "Software Pain-Point Intel";
  header.appendChild(h1);

  const sub = document.createElement("p");
  sub.className = "smi-subhead";
  sub.textContent = `Release ${dashboard.run_id} · generated ${formatDate(dashboard.generated_at)}`;
  header.appendChild(sub);

  if (stale && publishedAt) {
    const warn = document.createElement("aside");
    warn.className = "smi-stale";
    warn.textContent = `Data is stale — last refresh ${formatDate(publishedAt)}. The weekly job may have failed.`;
    header.appendChild(warn);
  }

  root.appendChild(header);
}

function renderHeuristicBanner(root: HTMLElement): void {
  const banner = document.createElement("aside");
  banner.className = "smi-heuristic-banner";
  const strong = document.createElement("strong");
  strong.textContent = "Heuristic-only mode.";
  banner.appendChild(strong);
  banner.appendChild(
    document.createTextNode(
      " The pipeline ran without an Anthropic API key — cluster summaries come from keyword heuristics rather than LLM refinement.",
    ),
  );
  root.appendChild(banner);
}

function renderFooter(root: HTMLElement, dashboard: Dashboard): void {
  const footer = document.createElement("footer");
  footer.className = "smi-footer";
  const p = document.createElement("p");
  p.innerHTML =
    'Methodology in <a href="https://github.com/priyeshkpandey/social-media-intel/blob/main/METHODOLOGY.md">METHODOLOGY.md</a> · ' +
    `Schema v${dashboard.schema_version} · ` +
    '<a href="https://github.com/priyeshkpandey/social-media-intel">source on GitHub</a>';
  footer.appendChild(p);
  root.appendChild(footer);
}

function renderError(root: HTMLElement, err: unknown): void {
  const message = err instanceof Error ? err.message : String(err);
  const article = document.createElement("article");
  article.className = "smi-error";
  const h2 = document.createElement("h2");
  h2.textContent = "Couldn't load the dashboard";
  const p = document.createElement("p");
  p.textContent = message;
  article.appendChild(h2);
  article.appendChild(p);
  root.innerHTML = "";
  root.appendChild(article);
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

main();
