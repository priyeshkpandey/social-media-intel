import type { Cluster, Dashboard, Opportunity } from "../data";

export function renderHero(root: HTMLElement, dashboard: Dashboard): void {
  const section = document.createElement("section");
  section.className = "smi-hero";

  const heading = document.createElement("h2");
  heading.textContent = "Top 10 opportunities this week";
  section.appendChild(heading);

  if (dashboard.narrative && dashboard.narrative.top_10.length > 0) {
    section.appendChild(renderHeadline(dashboard.narrative.headline));
    section.appendChild(renderOpportunityGrid(dashboard.narrative.top_10));
    if (dashboard.narrative.honorable_mentions.length > 0) {
      section.appendChild(renderHonorableMentions(dashboard.narrative.honorable_mentions));
    }
  } else {
    section.appendChild(renderHeuristicFallback(dashboard.clusters));
  }

  root.appendChild(section);
}

function renderHeadline(headline: string): HTMLElement {
  const p = document.createElement("p");
  p.className = "smi-headline";
  p.textContent = headline;
  return p;
}

function renderOpportunityGrid(opps: Opportunity[]): HTMLElement {
  const grid = document.createElement("div");
  grid.className = "smi-opportunity-grid";
  for (const opp of opps) {
    grid.appendChild(renderOpportunityCard(opp));
  }
  return grid;
}

function renderOpportunityCard(o: Opportunity): HTMLElement {
  const card = document.createElement("article");
  card.className = "smi-opportunity-card";
  card.dataset.rank = String(o.rank);
  card.dataset.evidence = o.evidence_cluster_ids.join(",");

  const header = document.createElement("header");
  const rank = document.createElement("span");
  rank.className = "smi-rank";
  rank.textContent = `#${o.rank}`;
  const title = document.createElement("h3");
  title.textContent = o.title;
  header.appendChild(rank);
  header.appendChild(title);
  card.appendChild(header);

  card.appendChild(labeledPara("Pain", o.pain, "smi-pain"));
  card.appendChild(labeledPara("Pitch", o.pitch, "smi-pitch"));
  card.appendChild(labeledPara("Why now", o.why_now, "smi-why-now"));

  const footer = document.createElement("footer");
  footer.appendChild(badge(o.target_role, "smi-badge-role"));
  footer.appendChild(badge(o.estimated_band, "smi-badge-band"));
  card.appendChild(footer);

  return card;
}

function labeledPara(label: string, body: string, cls: string): HTMLElement {
  const p = document.createElement("p");
  p.className = cls;
  const strong = document.createElement("strong");
  strong.textContent = `${label}: `;
  p.appendChild(strong);
  p.appendChild(document.createTextNode(body));
  return p;
}

function badge(text: string, cls: string): HTMLElement {
  const span = document.createElement("span");
  span.className = `smi-badge ${cls}`;
  span.textContent = text;
  return span;
}

function renderHonorableMentions(mentions: string[]): HTMLElement {
  const wrap = document.createElement("aside");
  wrap.className = "smi-honorable";
  const title = document.createElement("h4");
  title.textContent = "Honorable mentions";
  wrap.appendChild(title);
  const ul = document.createElement("ul");
  for (const m of mentions) {
    const li = document.createElement("li");
    li.textContent = m;
    ul.appendChild(li);
  }
  wrap.appendChild(ul);
  return wrap;
}

function renderHeuristicFallback(clusters: Cluster[]): HTMLElement {
  const wrap = document.createElement("div");

  const note = document.createElement("p");
  note.className = "smi-headline smi-headline-fallback";
  note.textContent =
    "Heuristic ranking — LLM narrative unavailable. Showing the top 10 clusters by opportunity score.";
  wrap.appendChild(note);

  const ranked = [...clusters].sort((a, b) => b.opportunity - a.opportunity).slice(0, 10);

  const grid = document.createElement("div");
  grid.className = "smi-opportunity-grid";

  ranked.forEach((c, idx) => {
    const card = document.createElement("article");
    card.className = "smi-opportunity-card";
    card.dataset.clusterId = c.id;

    const header = document.createElement("header");
    const rank = document.createElement("span");
    rank.className = "smi-rank";
    rank.textContent = `#${idx + 1}`;
    const title = document.createElement("h3");
    title.textContent = c.title;
    header.appendChild(rank);
    header.appendChild(title);
    card.appendChild(header);

    if (c.cost.summary && c.cost.summary !== "no cost data") {
      card.appendChild(labeledPara("Perceived cost", c.cost.summary, "smi-pain"));
    }

    const topRole = c.role_top[0];
    if (topRole) {
      card.appendChild(
        labeledPara(
          "Top role",
          `${topRole.role} (${Math.round(topRole.share * 100)}%)`,
          "smi-why-now",
        ),
      );
    }

    const footer = document.createElement("footer");
    footer.appendChild(badge(c.feasibility, "smi-badge-feasibility"));
    footer.appendChild(badge(c.impl_cost_band, "smi-badge-band"));
    footer.appendChild(badge(`${c.post_count} posts`, "smi-badge-count"));
    card.appendChild(footer);

    grid.appendChild(card);
  });

  wrap.appendChild(grid);
  return wrap;
}
