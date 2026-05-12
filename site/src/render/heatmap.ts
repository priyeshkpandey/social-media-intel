import type { Cluster, Dashboard } from "../data";
import { bindResize, echarts } from "../echarts-setup";

const TOP_N_FOR_HEATMAP = 15;

// Canonical role list — mirrors ROLES in pipeline/config.py. Keeping this
// alphabetized + stable so the heatmap columns don't reshuffle week-to-week.
const ROLE_ORDER = [
  "engineer",
  "manager",
  "product_manager",
  "project_manager",
  "qa",
  "devops",
  "sre",
  "founder",
  "designer",
  "data",
  "security",
  "support",
  "customer",
  "other",
];

export function renderHeatmap(root: HTMLElement, dashboard: Dashboard): void {
  const section = document.createElement("section");
  section.className = "smi-chart-section";

  const heading = document.createElement("h2");
  heading.textContent = "Cluster × role demography";
  section.appendChild(heading);

  const hint = document.createElement("p");
  hint.className = "smi-hint";
  hint.textContent =
    "Share of posts per role for the top 15 clusters. Bright cells = role concentration.";
  section.appendChild(hint);

  const top = [...dashboard.clusters]
    .sort((a, b) => b.opportunity - a.opportunity)
    .slice(0, TOP_N_FOR_HEATMAP);

  if (top.length === 0) {
    section.appendChild(emptyMessage("No clusters available."));
    root.appendChild(section);
    return;
  }

  // Restrict columns to roles that actually appear in this batch — uncluttered.
  const presentRoles = new Set<string>();
  for (const c of top) for (const r of c.role_top) presentRoles.add(r.role);
  const cols = ROLE_ORDER.filter((r) => presentRoles.has(r));
  if (cols.length === 0) {
    section.appendChild(emptyMessage("No role data available."));
    root.appendChild(section);
    return;
  }

  const container = document.createElement("div");
  container.className = "smi-chart-container";
  container.style.height = `${Math.max(280, top.length * 28 + 120)}px`;
  section.appendChild(container);
  root.appendChild(section);

  const chart = echarts.init(container);
  chart.setOption(buildOption(top, cols));
  bindResize(chart, container);
}

function buildOption(clusters: Cluster[], cols: string[]) {
  const rowLabels = clusters.map((c) => truncate(c.title, 38));
  const cells: Array<[number, number, number]> = [];

  clusters.forEach((c, y) => {
    const shareByRole = new Map(c.role_top.map((r) => [r.role, r.share]));
    cols.forEach((role, x) => {
      cells.push([x, y, shareByRole.get(role) ?? 0]);
    });
  });

  return {
    tooltip: {
      position: "top",
      formatter: (info: unknown) => {
        const p = info as { value: [number, number, number] };
        const role = cols[p.value[0]];
        const cluster = clusters[p.value[1]];
        if (!role || !cluster) return "";
        const pct = Math.round(p.value[2] * 100);
        return `<strong>${escapeHtml(cluster.title)}</strong><br/>${escapeHtml(role)}: ${pct}%`;
      },
    },
    grid: { left: 220, right: 60, top: 40, bottom: 60 },
    xAxis: {
      type: "category",
      data: cols,
      splitArea: { show: true },
      axisLabel: { rotate: 30, fontSize: 11 },
    },
    yAxis: {
      type: "category",
      data: rowLabels,
      inverse: true,
      splitArea: { show: true },
      axisLabel: { fontSize: 11 },
    },
    visualMap: {
      min: 0,
      max: 1,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 10,
      inRange: { color: ["#f1f5f9", "#4a90e2", "#0a3a73"] },
      formatter: (v: number) => `${Math.round(v * 100)}%`,
    },
    series: [
      {
        type: "heatmap",
        data: cells,
        label: {
          show: true,
          formatter: (params: { value: [number, number, number] }) => {
            const v = params.value[2];
            return v >= 0.05 ? `${Math.round(v * 100)}%` : "";
          },
          fontSize: 10,
        },
        emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(0,0,0,0.3)" } },
      },
    ],
  };
}

function emptyMessage(text: string): HTMLElement {
  const p = document.createElement("p");
  p.className = "smi-empty";
  p.textContent = text;
  return p;
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n - 1) + "…";
}

function escapeHtml(s: string): string {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
