import type { Cluster, Dashboard } from "../data";
import { bindResize, echarts } from "../echarts-setup";

const TOP_N_FOR_TIMESERIES = 15;

export function renderTimeseries(root: HTMLElement, dashboard: Dashboard): void {
  const section = document.createElement("section");
  section.className = "smi-chart-section";

  const heading = document.createElement("h2");
  heading.textContent = "Activity timeline";
  section.appendChild(heading);

  const hint = document.createElement("p");
  hint.className = "smi-hint";
  hint.textContent =
    "Daily post counts for the top 15 clusters in this run (based on representative posts). " +
    "Multi-month trends will fill in as weekly releases accumulate.";
  section.appendChild(hint);

  const topClusters = [...dashboard.clusters]
    .sort((a, b) => b.opportunity - a.opportunity)
    .slice(0, TOP_N_FOR_TIMESERIES);

  if (topClusters.length === 0) {
    section.appendChild(emptyMessage("No clusters to plot."));
    root.appendChild(section);
    return;
  }

  const dayRange = collectDayRange(topClusters);
  if (dayRange.length === 0) {
    section.appendChild(emptyMessage("No representative posts with timestamps."));
    root.appendChild(section);
    return;
  }

  const container = document.createElement("div");
  container.className = "smi-chart-container";
  container.style.height = "420px";
  section.appendChild(container);
  root.appendChild(section);

  const chart = echarts.init(container);
  chart.setOption(buildOption(topClusters, dayRange));
  bindResize(chart, container);
}

function collectDayRange(clusters: Cluster[]): string[] {
  const set = new Set<string>();
  for (const c of clusters) {
    for (const p of c.representative_posts) {
      set.add(p.posted_at.slice(0, 10));
    }
  }
  return [...set].sort();
}

function buildOption(clusters: Cluster[], days: string[]) {
  const series = clusters.map((c) => {
    const counts = new Map<string, number>();
    for (const p of c.representative_posts) {
      const day = p.posted_at.slice(0, 10);
      counts.set(day, (counts.get(day) ?? 0) + 1);
    }
    return {
      name: c.title,
      type: "line",
      stack: "total",
      smooth: false,
      symbol: "none",
      areaStyle: { opacity: 0.7 },
      emphasis: { focus: "series" },
      data: days.map((d) => [d, counts.get(d) ?? 0]),
    };
  });

  return {
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross", label: { backgroundColor: "#6a7985" } },
    },
    legend: {
      type: "scroll",
      top: 0,
      data: clusters.map((c) => c.title),
      textStyle: { fontSize: 11 },
    },
    grid: { left: 50, right: 20, top: 50, bottom: 60 },
    xAxis: { type: "time" },
    yAxis: { type: "value", name: "Posts/day", nameGap: 30 },
    dataZoom: [
      { type: "inside", start: 0, end: 100 },
      { type: "slider", start: 0, end: 100, height: 18, bottom: 10 },
    ],
    series,
  };
}

function emptyMessage(text: string): HTMLElement {
  const p = document.createElement("p");
  p.className = "smi-empty";
  p.textContent = text;
  return p;
}
