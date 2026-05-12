import type { Cluster, Dashboard } from "../data";

type SortKey = "title" | "opportunity" | "frequency_per_week" | "feasibility" | "impl_cost_band" | "post_count";
type SortDir = "asc" | "desc";

interface Column {
  key: SortKey;
  label: string;
  align?: "right";
  render: (c: Cluster) => string;
}

const COLUMNS: Column[] = [
  { key: "title", label: "Cluster", render: (c) => c.title },
  { key: "opportunity", label: "Opp.", align: "right", render: (c) => c.opportunity.toFixed(1) },
  { key: "frequency_per_week", label: "Posts/wk", align: "right", render: (c) => c.frequency_per_week.toFixed(1) },
  { key: "feasibility", label: "Feasibility", render: (c) => c.feasibility },
  { key: "impl_cost_band", label: "Impl. band", render: (c) => c.impl_cost_band },
  { key: "post_count", label: "# posts", align: "right", render: (c) => String(c.post_count) },
];

const NUMERIC: Record<SortKey, boolean> = {
  title: false,
  opportunity: true,
  frequency_per_week: true,
  feasibility: false,
  impl_cost_band: false,
  post_count: true,
};

export function renderTable(
  root: HTMLElement,
  dashboard: Dashboard,
  onClusterClick: (clusterId: string) => void,
): void {
  const section = document.createElement("section");
  section.className = "smi-table-section";

  const heading = document.createElement("h2");
  heading.textContent = "Cluster explorer";
  section.appendChild(heading);

  // Search input
  const controls = document.createElement("div");
  controls.className = "smi-table-controls";
  const search = document.createElement("input");
  search.type = "search";
  search.placeholder = "Filter by title…";
  search.className = "smi-table-search";
  controls.appendChild(search);
  section.appendChild(controls);

  const tableWrap = document.createElement("div");
  tableWrap.className = "smi-table-wrap";
  const table = document.createElement("table");
  table.className = "smi-table";

  const thead = document.createElement("thead");
  const headerRow = document.createElement("tr");
  COLUMNS.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col.label;
    th.dataset.key = col.key;
    if (col.align === "right") th.classList.add("smi-cell-right");
    th.classList.add("smi-th-sortable");
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  section.appendChild(tableWrap);
  root.appendChild(section);

  // State
  let sortKey: SortKey = "opportunity";
  let sortDir: SortDir = "desc";
  let query = "";

  const draw = (): void => {
    const filtered = query
      ? dashboard.clusters.filter((c) => c.title.toLowerCase().includes(query))
      : [...dashboard.clusters];
    filtered.sort(comparator(sortKey, sortDir));

    tbody.replaceChildren();
    if (filtered.length === 0) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = COLUMNS.length;
      td.className = "smi-empty";
      td.textContent = "No clusters match the filter.";
      tr.appendChild(td);
      tbody.appendChild(tr);
      return;
    }

    for (const c of filtered) {
      const tr = document.createElement("tr");
      tr.dataset.clusterId = c.id;
      tr.tabIndex = 0;
      for (const col of COLUMNS) {
        const td = document.createElement("td");
        td.textContent = col.render(c);
        if (col.align === "right") td.classList.add("smi-cell-right");
        if (col.key === "feasibility") td.classList.add(`smi-feas-${c.feasibility}`);
        tr.appendChild(td);
      }
      tr.addEventListener("click", () => onClusterClick(c.id));
      tr.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClusterClick(c.id);
        }
      });
      tbody.appendChild(tr);
    }

    // Update header sort indicators
    headerRow.querySelectorAll("th").forEach((th) => {
      const key = th.dataset.key as SortKey | undefined;
      th.classList.remove("smi-sort-asc", "smi-sort-desc");
      if (key === sortKey) {
        th.classList.add(sortDir === "asc" ? "smi-sort-asc" : "smi-sort-desc");
      }
    });
  };

  headerRow.querySelectorAll("th").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.key as SortKey | undefined;
      if (!key) return;
      if (sortKey === key) {
        sortDir = sortDir === "asc" ? "desc" : "asc";
      } else {
        sortKey = key;
        sortDir = NUMERIC[key] ? "desc" : "asc";
      }
      draw();
    });
  });

  search.addEventListener("input", () => {
    query = search.value.trim().toLowerCase();
    draw();
  });

  draw();
}

function comparator(key: SortKey, dir: SortDir): (a: Cluster, b: Cluster) => number {
  const mult = dir === "asc" ? 1 : -1;
  return (a, b) => {
    const av = (a as unknown as Record<string, unknown>)[key];
    const bv = (b as unknown as Record<string, unknown>)[key];
    if (typeof av === "number" && typeof bv === "number") {
      return (av - bv) * mult;
    }
    return String(av).localeCompare(String(bv)) * mult;
  };
}
