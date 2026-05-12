import type { Dashboard } from "../data";

interface Tile {
  label: string;
  value: string;
  hint?: string;
}

export function renderKpi(root: HTMLElement, dashboard: Dashboard): void {
  const tiles: Tile[] = [
    {
      label: "Posts this week",
      value: dashboard.kpi.total_posts_this_week.toLocaleString(),
      hint: "Across all sources (Reddit, HN, dev.to, Lobsters, Stack Overflow).",
    },
    {
      label: "Active clusters",
      value: dashboard.kpi.active_clusters.toLocaleString(),
      hint: "Distinct pain-point clusters observed in this run.",
    },
    {
      label: "New clusters",
      value: dashboard.kpi.new_clusters_this_week.toLocaleString(),
      hint: "Clusters first observed in the last 7 days.",
    },
    {
      label: "Mean opportunity",
      value: dashboard.kpi.mean_opportunity.toFixed(1),
      hint: "Average heuristic opportunity score (0–100).",
    },
  ];

  const section = document.createElement("section");
  section.className = "smi-kpi-strip";
  section.setAttribute("aria-label", "Weekly key metrics");

  for (const tile of tiles) {
    const el = document.createElement("article");
    el.className = "smi-kpi-tile";
    const label = document.createElement("p");
    label.className = "smi-kpi-label";
    label.textContent = tile.label;
    const value = document.createElement("p");
    value.className = "smi-kpi-value";
    value.textContent = tile.value;
    el.appendChild(label);
    el.appendChild(value);
    if (tile.hint) el.title = tile.hint;
    section.appendChild(el);
  }

  root.appendChild(section);
}
