import type { Cluster, Dashboard } from "../data";
import { bindResize, echarts } from "../echarts-setup";

export function renderTreemap(
  root: HTMLElement,
  dashboard: Dashboard,
  onClusterClick: (clusterId: string) => void,
): void {
  const section = document.createElement("section");
  section.className = "smi-chart-section";

  const heading = document.createElement("h2");
  heading.textContent = "Pain-point treemap";
  section.appendChild(heading);

  const hint = document.createElement("p");
  hint.className = "smi-hint";
  hint.textContent = "Tile size = weekly frequency. Color = opportunity score (red → green). Click any tile to drill in.";
  section.appendChild(hint);

  if (dashboard.clusters.length === 0) {
    section.appendChild(emptyMessage("No clusters in this run."));
    root.appendChild(section);
    return;
  }

  const container = document.createElement("div");
  container.className = "smi-chart-container";
  container.style.height = "460px";
  section.appendChild(container);
  root.appendChild(section);

  const chart = echarts.init(container);
  chart.setOption(buildOption(dashboard.clusters));
  bindResize(chart, container);

  chart.on("click", (params) => {
    const data = params.data as { cluster_id?: string } | undefined;
    if (data?.cluster_id) onClusterClick(data.cluster_id);
  });
}

function buildOption(clusters: Cluster[]) {
  const data = clusters.map((c) => ({
    name: c.title,
    value: Math.max(c.frequency_per_week, 0.1),
    cluster_id: c.id,
    opportunity: c.opportunity,
    feasibility: c.feasibility,
    impl_cost_band: c.impl_cost_band,
    post_count: c.post_count,
  }));

  return {
    tooltip: {
      formatter: (info: unknown) => {
        const p = info as { name: string; data: { opportunity: number; feasibility: string; impl_cost_band: string; post_count: number } };
        const d = p.data;
        return [
          `<strong>${escapeHtml(p.name)}</strong>`,
          `Opportunity: ${d.opportunity.toFixed(1)}`,
          `Feasibility: ${escapeHtml(d.feasibility)}`,
          `Impl. band: ${escapeHtml(d.impl_cost_band)}`,
          `Posts: ${d.post_count}`,
        ].join("<br/>");
      },
    },
    visualMap: {
      type: "continuous",
      min: 0,
      max: 100,
      dimension: "opportunity",
      inRange: { color: ["#c0392b", "#f1c40f", "#27ae60"] },
      text: ["High opp.", "Low opp."],
      orient: "horizontal",
      left: "right",
      top: 0,
      itemWidth: 12,
      itemHeight: 80,
    },
    series: [
      {
        type: "treemap",
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        label: {
          show: true,
          formatter: "{b}",
          overflow: "truncate",
        },
        upperLabel: { show: false },
        itemStyle: { borderColor: "#fff", borderWidth: 1, gapWidth: 1 },
        data,
        visualDimension: 1, // index of "opportunity" in encoded fields below
        encode: { value: "value", tooltip: ["opportunity", "feasibility", "impl_cost_band", "post_count"] },
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

function escapeHtml(s: string): string {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
