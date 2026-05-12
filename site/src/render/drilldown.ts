import type { Cluster, Dashboard, Post } from "../data";

export function createDrilldownOpener(
  dashboard: Dashboard,
): (clusterId: string) => void {
  const dialog = document.createElement("dialog");
  dialog.id = "smi-drilldown";
  dialog.className = "smi-drilldown";
  document.body.appendChild(dialog);

  // Close on backdrop click
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) dialog.close();
  });

  const byId = new Map(dashboard.clusters.map((c) => [c.id, c]));

  return (clusterId: string) => {
    const cluster = byId.get(clusterId);
    if (!cluster) return;
    dialog.replaceChildren(...buildContent(cluster, () => dialog.close()));
    dialog.showModal();
  };
}

function buildContent(cluster: Cluster, onClose: () => void): Node[] {
  const nodes: Node[] = [];

  const header = document.createElement("header");
  header.className = "smi-drilldown-header";

  const titleWrap = document.createElement("div");
  const title = document.createElement("h2");
  title.textContent = cluster.title;
  titleWrap.appendChild(title);

  if (cluster.synthesis?.one_line_pain) {
    const sub = document.createElement("p");
    sub.className = "smi-drilldown-sub";
    sub.textContent = cluster.synthesis.one_line_pain;
    titleWrap.appendChild(sub);
  }
  header.appendChild(titleWrap);

  const close = document.createElement("button");
  close.type = "button";
  close.className = "smi-drilldown-close";
  close.setAttribute("aria-label", "Close");
  close.textContent = "×";
  close.addEventListener("click", onClose);
  header.appendChild(close);

  nodes.push(header);

  // Scored dimensions
  nodes.push(renderDimensions(cluster));

  // Synthesis details (if present)
  if (cluster.synthesis) {
    nodes.push(renderSynthesis(cluster.synthesis));
  }

  // Representative posts
  nodes.push(renderPosts(cluster.representative_posts));

  return nodes;
}

function renderDimensions(c: Cluster): HTMLElement {
  const grid = document.createElement("div");
  grid.className = "smi-dim-grid";

  const entries: Array<[string, string]> = [
    ["Opportunity", c.opportunity.toFixed(1)],
    ["Frequency/wk", c.frequency_per_week.toFixed(1)],
    ["Freq. z-score", c.frequency_zscore.toFixed(2)],
    ["Feasibility", c.feasibility],
    ["Impl. band", c.impl_cost_band],
    ["Posts", String(c.post_count)],
    ["First seen", c.first_seen.slice(0, 10)],
    ["Last seen", c.last_seen.slice(0, 10)],
  ];

  for (const [label, value] of entries) {
    const tile = document.createElement("div");
    tile.className = "smi-dim-tile";
    const l = document.createElement("p");
    l.className = "smi-dim-label";
    l.textContent = label;
    const v = document.createElement("p");
    v.className = "smi-dim-value";
    v.textContent = value;
    tile.appendChild(l);
    tile.appendChild(v);
    grid.appendChild(tile);
  }

  // Cost summary as its own row spanning the grid
  const cost = document.createElement("div");
  cost.className = "smi-dim-cost";
  const costLabel = document.createElement("strong");
  costLabel.textContent = "Cost evidence: ";
  cost.appendChild(costLabel);
  cost.appendChild(document.createTextNode(c.cost.summary));
  if (c.cost.sample_count > 0) {
    const meta = document.createElement("span");
    meta.className = "smi-dim-cost-meta";
    meta.textContent = ` (${c.cost.sample_count} mention${c.cost.sample_count === 1 ? "" : "s"})`;
    cost.appendChild(meta);
  }

  // Demography
  const demo = document.createElement("div");
  demo.className = "smi-dim-demo";
  const demoLabel = document.createElement("strong");
  demoLabel.textContent = "Demography: ";
  demo.appendChild(demoLabel);
  if (c.role_top.length === 0) {
    demo.appendChild(document.createTextNode("no role data"));
  } else {
    const parts = c.role_top.map((r) => `${r.role} ${Math.round(r.share * 100)}%`);
    demo.appendChild(document.createTextNode(parts.join(" · ")));
  }

  const wrap = document.createElement("section");
  wrap.className = "smi-drilldown-dimensions";
  const h3 = document.createElement("h3");
  h3.textContent = "Scored dimensions";
  wrap.appendChild(h3);
  wrap.appendChild(grid);
  wrap.appendChild(cost);
  wrap.appendChild(demo);
  return wrap;
}

function renderSynthesis(s: NonNullable<Cluster["synthesis"]>): HTMLElement {
  const wrap = document.createElement("section");
  wrap.className = "smi-drilldown-synthesis";

  const h3 = document.createElement("h3");
  h3.textContent = "Refined synthesis";
  wrap.appendChild(h3);

  const conf = document.createElement("p");
  conf.className = "smi-synth-conf";
  conf.textContent = `Confidence: ${(s.confidence * 100).toFixed(0)}%`;
  wrap.appendChild(conf);

  const dl = document.createElement("dl");
  const rows: Array<[string, string]> = [
    ["Role demographics", s.role_demographics],
    ["Perceived cost", s.perceived_cost_summary],
    ["Opportunity pitch", s.opportunity_pitch],
  ];
  for (const [label, body] of rows) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = body;
    dl.appendChild(dt);
    dl.appendChild(dd);
  }
  wrap.appendChild(dl);
  return wrap;
}

function renderPosts(posts: Post[]): HTMLElement {
  const wrap = document.createElement("section");
  wrap.className = "smi-drilldown-posts";

  const h3 = document.createElement("h3");
  h3.textContent = `Representative posts (${posts.length})`;
  wrap.appendChild(h3);

  if (posts.length === 0) {
    const p = document.createElement("p");
    p.className = "smi-empty";
    p.textContent = "No representative posts available.";
    wrap.appendChild(p);
    return wrap;
  }

  const list = document.createElement("ol");
  list.className = "smi-post-list";

  for (const post of posts) {
    const li = document.createElement("li");
    li.className = "smi-post-item";

    const meta = document.createElement("div");
    meta.className = "smi-post-meta";

    const source = document.createElement("a");
    source.href = post.url;
    source.target = "_blank";
    source.rel = "noopener noreferrer";
    source.textContent = `${post.source}${post.role ? ` · ${post.role}` : ""}`;
    meta.appendChild(source);

    const date = document.createElement("span");
    date.className = "smi-post-date";
    date.textContent = post.posted_at.slice(0, 10);
    meta.appendChild(date);

    const score = document.createElement("span");
    score.className = "smi-post-score";
    score.textContent = `score ${post.score} · ${post.replies_count} replies`;
    meta.appendChild(score);

    li.appendChild(meta);

    const text = document.createElement("p");
    text.className = "smi-post-text";
    text.textContent = post.text;
    li.appendChild(text);

    list.appendChild(li);
  }

  wrap.appendChild(list);
  return wrap;
}
