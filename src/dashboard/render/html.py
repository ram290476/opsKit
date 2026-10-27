"""Self-contained interactive HTML: a left-to-right flow graph you drill through by clicking.

Everything is inline (CSS, SVG sparklines, vanilla JS, JSON state), so the file opens from disk,
from an S3 bucket or as a CI artifact with no CDN or server. Cards are rendered server-side with
id="node-<entity id>" (plus a detail panel id="detail-<entity id>"); the script only arranges them
into columns, draws the edges and tracks the selection in location.hash, so the browser back
button and shared links work.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from ..models import Direction, Entity, Health, LEVELS, MetricResult, TriageResult

COLORS = {Health.OK: "#2e7d32", Health.WARN: "#b7791f", Health.CRITICAL: "#c62828", Health.UNKNOWN: "#64748b"}
CARD_METRICS = 2


def sparkline_svg(m: MetricResult, width: int = 120, height: int = 30, show_threshold: bool = True) -> str:
    """Inline SVG polyline for one metric, with warn line, anomaly onset marker and last point."""
    pts = m.series.points
    color = COLORS[m.health]
    if not pts:
        return f'<svg class="spark" width="{width}" height="{height}" role="img" aria-label="no data"></svg>'
    lo, hi = min(pts), max(pts)
    if m.threshold and show_threshold:
        lo, hi = min(lo, m.threshold.warn), max(hi, m.threshold.warn)
    span = (hi - lo) or 1.0
    pad = 3
    n = max(1, len(pts) - 1)

    def xy(i: int, v: float) -> tuple[float, float]:
        return (round(pad + i * (width - 2 * pad) / n, 1),
                round(height - pad - (v - lo) / span * (height - 2 * pad), 1))

    coords = [xy(i, v) for i, v in enumerate(pts)]
    poly = " ".join(f"{x},{y}" for x, y in coords)
    area = f"{coords[0][0]},{height - pad} {poly} {coords[-1][0]},{height - pad}"
    parts = [f'<svg class="spark" width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
             f'role="img" aria-label="{html.escape(m.series.name)} trend">',
             f'<polygon points="{area}" fill="{color}" fill-opacity="0.12"/>']
    if m.threshold and show_threshold:
        _, ty = xy(0, m.threshold.warn)
        parts.append(f'<line x1="{pad}" x2="{width - pad}" y1="{ty}" y2="{ty}" stroke="#b7791f" '
                     f'stroke-dasharray="3 3" stroke-width="1" opacity="0.7"/>')
    if m.anomaly:
        ax, _ = coords[m.anomaly.onset_index]
        parts.append(f'<line class="onset" x1="{ax}" x2="{ax}" y1="0" y2="{height}" stroke="#c62828" '
                     f'stroke-width="1.2" stroke-dasharray="2 2"/>')
    parts.append(f'<polyline points="{poly}" fill="none" stroke="{color}" stroke-width="1.6" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')
    lx, ly = coords[-1]
    parts.append(f'<circle cx="{lx}" cy="{ly}" r="2.4" fill="{color}"/></svg>')
    return "".join(parts)


def _fmt(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.2f}".rstrip("0").rstrip(".")


def _trend_html(m: MetricResult) -> str:
    worse_up = m.threshold.higher_is_worse if m.threshold else True
    bad = (m.trend.direction == Direction.UP) == worse_up and m.trend.direction != Direction.FLAT
    cls = "flat" if m.trend.direction == Direction.FLAT else ("bad" if bad else "good")
    sign = "+" if m.trend.pct_change > 0 else ""
    return f'<span class="trend {cls}" title="recent half vs earlier half">{m.trend.arrow} {sign}{m.trend.pct_change:g}%</span>'


def _key_metrics(e: Entity) -> list[MetricResult]:
    """Worst first, then anomalous, then catalogue order: the two that best explain the card."""
    order = {m.series.name: i for i, m in enumerate(e.metrics)}
    return sorted(e.metrics, key=lambda m: (-m.health.rank, m.anomaly is None, order[m.series.name]))[:CARD_METRICS]


def _card(e: Entity, origin_id: str | None, path_ids: set[str], step_s: int) -> str:
    classes = ["card", e.health.value, f"own-{e.own_health.value}"]
    if e.id in path_ids:
        classes.append("on-path")
    if e.id == origin_id:
        classes.append("origin")
    badges = []
    if e.id == origin_id:
        badges.append('<span class="badge origin-badge">ROOT CAUSE</span>')
    if e.onset_index is not None and e.own_health.rank >= Health.WARN.rank:
        badges.append(f'<span class="badge anomaly" title="first anomalous point in window">'
                      f'anomaly t+{e.onset_index * step_s // 60}m</span>')
    if e.children:
        bad = sum(1 for c in e.children if c.health.rank >= Health.WARN.rank)
        badges.append(f'<span class="badge kids">{len(e.children)} {LEVELS[e.level.depth + 1].label.lower()}'
                      f'{f", {bad} unhealthy" if bad else ""}</span>')
    rows = "".join(
        f'<div class="m"><span class="mn">{html.escape(m.series.name)}</span>'
        f'<span class="mv {m.health.value}">{_fmt(m.series.latest)}<small>{html.escape(m.series.unit)}</small></span>'
        f'{_trend_html(m)}{sparkline_svg(m)}</div>' for m in _key_metrics(e))
    return (f'<div class="{" ".join(classes)}" id="node-{html.escape(e.id)}" data-id="{html.escape(e.id)}" '
            f'data-level="{e.level.depth}" tabindex="0" role="button" aria-label="{html.escape(e.level.singular)} '
            f'{html.escape(e.name)}, {e.health.value}">'
            f'<div class="ch"><span class="dot"></span><span class="lvl">{e.level.singular}</span></div>'
            f'<div class="nm">{html.escape(e.name)}</div><div class="badges">{"".join(badges)}</div>{rows}</div>')


def _detail(e: Entity, origin_id: str | None, step_s: int) -> str:
    attrs = "".join(f"<dt>{html.escape(str(k))}</dt><dd>{html.escape(str(v))}</dd>" for k, v in e.attrs.items())
    rows = []
    for m in e.metrics:
        th = (f"warn {'≥' if m.threshold.higher_is_worse else '≤'} {_fmt(m.threshold.warn)}, "
              f"crit {'≥' if m.threshold.higher_is_worse else '≤'} {_fmt(m.threshold.critical)}") if m.threshold else "-"
        an = (f'<span class="badge anomaly">{m.anomaly.reason} @ t+{m.anomaly.onset_index * step_s // 60}m</span>'
              if m.anomaly else "")
        rows.append(f'<tr class="{m.health.value}"><td><span class="dot {m.health.value}"></span>'
                    f'{html.escape(m.series.name)}</td><td>{sparkline_svg(m, 220, 44)}</td>'
                    f'<td class="num">{_fmt(m.series.latest)} {html.escape(m.series.unit)}</td><td>{_trend_html(m)}</td>'
                    f'<td>{th}</td><td>{an}</td><td class="src">{html.escape(m.series.source)}</td></tr>')
    origin_note = ('<p class="origin-note">This is the root-cause origin: the earliest anomaly in the '
                   'window, at the deepest level. Everything above it on the red path is a symptom.</p>'
                   if e.id == origin_id else "")
    return (f'<section class="detail" id="detail-{html.escape(e.id)}" hidden>'
            f'<h3><span class="dot {e.health.value}"></span>{e.level.singular}: {html.escape(e.name)} '
            f'<small>own {e.own_health.value}, subtree {e.health.value}</small></h3>{origin_note}'
            f'<dl>{attrs}</dl><table><thead><tr><th>metric</th><th>trend ({len(e.metrics[0].series.points) if e.metrics else 0} pts)</th>'
            f'<th>latest</th><th>change</th><th>threshold</th><th>anomaly</th><th>source</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></section>')


def _state(result: TriageResult) -> dict:
    return {
        "root": result.root.id,
        "origin": result.origin.id if result.origin else None,
        "path": [e.id for e in result.path],
        "levels": [lv.label for lv in LEVELS],
        "nodes": {e.id: {"name": e.name, "level": e.level.depth, "health": e.health.value,
                         "parent": e.parent_id, "children": [c.id for c in e.children]}
                  for e in result.root.walk()},
    }


def render_html(result: TriageResult, title: str | None = None, step_s: int = 60,
                generated_at: datetime | None = None, banner: str = "", source: str = "demo",
                auto_refresh_s: int = 0) -> str:
    """Return the full HTML document as a string.

    banner: warning strip under the header (e.g. "DEMO DATA - kube API unreachable").
    auto_refresh_s: >0 reloads the page on that interval, keeping the #selection (serve mode).
    """
    generated_at = generated_at or datetime.now(timezone.utc)
    origin_id = result.origin.id if result.origin else None
    path_ids = {e.id for e in result.path}
    entities = list(result.root.walk())
    cards = "".join(_card(e, origin_id, path_ids, step_s) for e in entities)
    details = "".join(_detail(e, origin_id, step_s) for e in entities)
    title = title or f"{result.root.name} triage"
    window_pts = len(result.root.series[0].points) if result.root.series else 0
    timeline = "".join(
        f'<li class="{e.own_health.value}"><a href="#{html.escape(e.id)}">t+{i * step_s // 60}m '
        f'{e.level.singular} <b>{html.escape(e.name)}</b></a></li>' for i, e in result.timeline)
    origin_txt = (f'Root cause: <b>{result.origin.level.singular} {html.escape(result.origin.name)}</b>'
                  if result.origin else "No anomaly origin found")
    state = json.dumps(_state(result)).replace("</", "<\\/")
    banner_html = f'<div class="banner" id="banner">{html.escape(banner)}</div>' if banner else ""
    refresh_js = (f"<script>setTimeout(function(){{location.reload();}}, {int(auto_refresh_s) * 1000});</script>"
                  if auto_refresh_s > 0 else "")
    return (_TEMPLATE
            .replace("%%TITLE%%", html.escape(title))
            .replace("%%HEALTH%%", result.root.health.value)
            .replace("%%HEALTH_UP%%", result.root.health.value.upper())
            .replace("%%CLUSTER%%", html.escape(result.root.name))
            .replace("%%WINDOW%%", f"{window_pts * step_s // 60} min window, {step_s}s step")
            .replace("%%GENERATED%%", generated_at.strftime("%Y-%m-%d %H:%M UTC"))
            .replace("%%ORIGIN%%", origin_txt)
            .replace("%%JUMP_DISABLED%%", "" if origin_id else " disabled")
            .replace("%%TIMELINE%%", timeline or "<li>no anomalies in window</li>")
            .replace("%%CARDS%%", cards)
            .replace("%%DETAILS%%", details)
            .replace("%%BANNER%%", banner_html)
            .replace("%%SOURCE%%", html.escape(source))
            .replace("%%REFRESH%%", refresh_js)
            .replace("%%STATE%%", state))


_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>%%TITLE%%</title>
<style>
:root{--ok:#2e7d32;--warn:#b7791f;--crit:#c62828;--unk:#64748b;--bg:#f6f7f9;--ink:#1f2937;--mut:#6b7280;--line:#d6dae1}
*{box-sizing:border-box}body{margin:0;font:13px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;background:var(--bg);color:var(--ink)}
header{display:flex;flex-wrap:wrap;gap:12px 24px;align-items:center;padding:12px 20px;background:#111827;color:#f9fafb}
header h1{font-size:16px;margin:0}header .meta{color:#9ca3af;font-size:12px}
.pill{padding:2px 10px;border-radius:999px;font-weight:700;font-size:12px}.pill.ok{background:var(--ok)}.pill.warn{background:var(--warn)}.pill.critical{background:var(--crit)}.pill.unknown{background:var(--unk)}
.flowsteps{display:flex;gap:6px;font-size:12px;color:#d1d5db}.flowsteps span{padding:2px 8px;border:1px solid #374151;border-radius:4px}.flowsteps b{color:#fff}
button.jump{margin-left:auto;background:var(--crit);color:#fff;border:0;border-radius:6px;padding:7px 14px;font-weight:700;cursor:pointer}button.jump:disabled{background:#4b5563;cursor:default}
nav.crumbs{display:flex;align-items:center;gap:6px;padding:10px 20px;background:#fff;border-bottom:1px solid var(--line);flex-wrap:wrap}
nav.crumbs a{color:#1d4ed8;text-decoration:none}nav.crumbs a:hover{text-decoration:underline}nav.crumbs .sep{color:var(--mut)}
nav.crumbs .back{margin-right:10px;padding:2px 8px;border:1px solid var(--line);border-radius:4px}
nav.crumbs label{margin-left:auto;color:var(--mut)}
.summary{display:flex;gap:24px;padding:8px 20px;align-items:baseline;flex-wrap:wrap}
.summary ol{display:flex;gap:6px;list-style:none;margin:0;padding:0;flex-wrap:wrap}.summary li a{display:block;padding:2px 8px;border-radius:4px;background:#fff;border:1px solid var(--line);color:var(--ink);text-decoration:none;font-size:12px}
.summary li.critical a{border-color:var(--crit)}.summary li.warn a{border-color:var(--warn)}.summary li a:hover{background:#eef2ff}
.summary li{display:flex;align-items:center;gap:6px;white-space:nowrap}.summary li+li:before{content:"\2192";color:var(--mut)}
#graph{position:relative;overflow-x:auto;padding:8px 20px 20px}
#edges{position:absolute;left:0;top:0;pointer-events:none;overflow:visible}
#cols{display:grid;grid-template-columns:repeat(6,minmax(200px,1fr));gap:36px;position:relative;min-width:1380px}
.col h2{font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--mut);margin:4px 0 8px;font-weight:600}
.col .empty{color:var(--mut);font-style:italic;font-size:12px;padding:8px 0}
.card{background:#fff;border:1px solid var(--line);border-left:5px solid var(--unk);border-radius:8px;padding:8px 10px;margin-bottom:12px;cursor:pointer;box-shadow:0 1px 2px rgba(0,0,0,.05);transition:box-shadow .15s,transform .15s;position:relative}
.card:hover,.card:focus{box-shadow:0 4px 14px rgba(0,0,0,.12);outline:none;transform:translateY(-1px)}
.card.ok{border-left-color:var(--ok)}.card.warn{border-left-color:var(--warn);background:#fffbeb}.card.critical{border-left-color:var(--crit);background:#fef2f2}
.card.selected{box-shadow:0 0 0 2px #1d4ed8,0 4px 14px rgba(0,0,0,.12)}
.card.on-path.critical,.card.on-path.warn{border-color:var(--crit)}
.card.origin{box-shadow:0 0 0 3px var(--crit),0 0 18px rgba(198,40,40,.45);animation:pulse 2s infinite}
@keyframes pulse{50%{box-shadow:0 0 0 3px var(--crit),0 0 4px rgba(198,40,40,.2)}}
.ch{display:flex;align-items:center;gap:6px;color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.05em}
.dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--unk);margin-right:4px}
.card.ok .dot,.dot.ok{background:var(--ok)}.card.warn .dot,.dot.warn{background:var(--warn)}.card.critical .dot,.dot.critical{background:var(--crit)}
.nm{font-weight:700;font-size:13px;margin:2px 0 4px;word-break:break-all}
.badges{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:4px}
.badge{font-size:10px;padding:1px 6px;border-radius:4px;background:#eef2f7;color:#374151;white-space:nowrap}
.badge.anomaly{background:#fde68a;color:#78350f}.badge.origin-badge{background:var(--crit);color:#fff;font-weight:700}
.m{display:grid;grid-template-columns:1fr auto;grid-template-areas:"n v" "s t";column-gap:6px;align-items:center;margin-top:4px}
.mn{grid-area:n;color:var(--mut);font-size:11px}.mv{grid-area:v;font-weight:700;text-align:right}.mv small{font-weight:400;color:var(--mut);margin-left:2px}
.mv.critical{color:var(--crit)}.mv.warn{color:var(--warn)}.m .spark{grid-area:s}.m .trend{grid-area:t;text-align:right}
.trend{font-size:11px;white-space:nowrap}.trend.bad{color:var(--crit)}.trend.good{color:var(--ok)}.trend.flat{color:var(--mut)}
#details{padding:0 20px 30px}.detail{background:#fff;border:1px solid var(--line);border-radius:8px;padding:12px 16px}
.detail h3{margin:0 0 6px;font-size:15px}.detail h3 small{color:var(--mut);font-weight:400;margin-left:8px}
.detail dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 12px;margin:6px 0 10px;font-size:12px}.detail dt{color:var(--mut)}.detail dd{margin:0}
.detail table{border-collapse:collapse;width:100%}.detail th,.detail td{text-align:left;padding:4px 8px;border-top:1px solid #eef0f3;vertical-align:middle}
.detail th{font-size:11px;color:var(--mut);font-weight:600}.detail td.num{font-weight:700;white-space:nowrap}.detail td.src{color:var(--mut);font-size:11px}
.detail tr.critical td:first-child{color:var(--crit);font-weight:700}.origin-note{background:#fef2f2;border-left:4px solid var(--crit);padding:6px 10px;margin:6px 0}
.banner{background:#fef3c7;color:#78350f;border-bottom:1px solid #f59e0b;padding:8px 20px;font-weight:600}
#store{display:none}.nojs #store{display:block;padding:20px}
footer{color:var(--mut);font-size:11px;padding:0 20px 20px}kbd{border:1px solid var(--line);border-radius:3px;padding:0 4px;background:#fff}
</style></head>
<body class="nojs">
<header>
  <h1>%%CLUSTER%%</h1><span class="pill %%HEALTH%%">%%HEALTH_UP%%</span>
  <span class="meta">%%WINDOW%% &middot; source: %%SOURCE%% &middot; generated %%GENERATED%%</span>
  <div class="flowsteps"><span>1. <b>See the trend</b></span><span>2. <b>Spot the anomaly</b></span><span>3. <b>Drill to the source</b></span></div>
  <button class="jump" id="jump"%%JUMP_DISABLED%% title="Expand the red path down to the root-cause origin (shortcut: J)">Jump to source &#8600;</button>
</header>
%%BANNER%%
<nav class="crumbs" id="crumbs" aria-label="breadcrumbs"></nav>
<div class="summary"><span>%%ORIGIN%%</span><span class="meta">Anomaly onset order:</span><ol>%%TIMELINE%%</ol></div>
<div id="graph"><svg id="edges"></svg><div id="cols"></div></div>
<div id="details">%%DETAILS%%</div>
<div id="store">%%CARDS%%</div>
<footer>Click a card to drill into its children; click it again to collapse. <kbd>Esc</kbd>/<kbd>Backspace</kbd> goes back one level, <kbd>J</kbd> jumps to the root-cause origin, <kbd>U</kbd> toggles healthy cards. Dashed amber line = warn threshold, dashed red line = anomaly onset.</footer>
<script id="state" type="application/json">%%STATE%%</script>
<script>
(function(){
  "use strict";
  var S = JSON.parse(document.getElementById("state").textContent);
  var N = S.nodes, onPath = {}, store = document.getElementById("store");
  S.path.forEach(function(id){ onPath[id] = true; });
  document.body.classList.remove("nojs");
  var cols = document.getElementById("cols"), edges = document.getElementById("edges");
  var crumbs = document.getElementById("crumbs"), onlyBad = false, sel = [S.root];

  function card(id){ return document.getElementById("node-" + id); }
  function chain(id){ var out = []; while (id){ out.unshift(id); id = N[id].parent; } return out; }
  function bad(id){ return N[id].health === "warn" || N[id].health === "critical"; }

  function render(){
    // park all cards back in the store, then lay out one column per level along the selection
    Array.prototype.forEach.call(document.querySelectorAll(".card"), function(c){ c.classList.remove("selected"); store.appendChild(c); });
    cols.innerHTML = "";
    S.levels.forEach(function(label, depth){
      var col = document.createElement("div"); col.className = "col"; col.dataset.depth = depth;
      var h = document.createElement("h2"); h.textContent = label; col.appendChild(h);
      var ids = depth === 0 ? [S.root] : (sel[depth - 1] ? N[sel[depth - 1]].children : []);
      var shown = ids.filter(function(id){ return !onlyBad || bad(id) || sel[depth] === id; });
      // unhealthy first so the red path reads top-down
      var rank = {critical: 0, warn: 1, unknown: 2, ok: 3};
      shown.sort(function(a, b){ return rank[N[a].health] - rank[N[b].health]; });
      shown.forEach(function(id){ var c = card(id); if (c){ col.appendChild(c); if (sel[depth] === id) c.classList.add("selected"); } });
      if (!shown.length){
        var e = document.createElement("div"); e.className = "empty";
        e.textContent = ids.length ? (ids.length + " healthy hidden") : (depth && sel[depth - 1] ? "no children" : "select a card to the left");
        col.appendChild(e);
      }
      cols.appendChild(col);
    });
    // breadcrumbs + back link
    crumbs.innerHTML = "";
    var last = sel[sel.length - 1];
    var back = document.createElement("a"); back.className = "back"; back.textContent = "\u2190 Back";
    back.href = "#" + (N[last].parent || S.root); crumbs.appendChild(back);
    sel.forEach(function(id, i){
      if (i){ var s = document.createElement("span"); s.className = "sep"; s.textContent = "\u203a"; crumbs.appendChild(s); }
      var a = document.createElement("a"); a.href = "#" + id; a.textContent = N[id].name;
      a.style.color = N[id].health === "critical" ? "var(--crit)" : (N[id].health === "warn" ? "var(--warn)" : "");
      crumbs.appendChild(a);
    });
    var lab = document.createElement("label");
    lab.innerHTML = '<input type="checkbox" id="onlybad"' + (onlyBad ? " checked" : "") + '> only unhealthy (U)';
    crumbs.appendChild(lab);
    document.getElementById("onlybad").onchange = function(){ onlyBad = this.checked; render(); };
    // detail panel for the deepest selection
    Array.prototype.forEach.call(document.querySelectorAll(".detail"), function(d){ d.hidden = true; });
    var d = document.getElementById("detail-" + last); if (d) d.hidden = false;
    requestAnimationFrame(drawEdges);
  }

  function drawEdges(){
    var g = document.getElementById("graph"), gb = g.getBoundingClientRect();
    edges.setAttribute("width", g.scrollWidth); edges.setAttribute("height", g.scrollHeight);
    var out = [];
    sel.forEach(function(pid){
      var p = card(pid); if (!p || !p.parentNode.classList.contains("col")) return;
      N[pid].children.forEach(function(cid){
        var c = card(cid); if (!c || !c.parentNode.classList.contains("col")) return;
        var a = p.getBoundingClientRect(), b = c.getBoundingClientRect();
        var x1 = a.right - gb.left + g.scrollLeft, y1 = a.top + a.height / 2 - gb.top;
        var x2 = b.left - gb.left + g.scrollLeft, y2 = b.top + Math.min(b.height / 2, 40) - gb.top;
        var red = onPath[pid] && onPath[cid], hot = bad(cid);
        var mx = (x1 + x2) / 2;
        out.push('<path d="M' + x1 + ',' + y1 + ' C' + mx + ',' + y1 + ' ' + mx + ',' + y2 + ' ' + x2 + ',' + y2 + '" fill="none" stroke="' +
          (red ? "#c62828" : hot ? "#e0a43a" : "#c3c9d2") + '" stroke-width="' + (red ? 3.5 : 1.5) + '"' + (red ? '' : ' stroke-dasharray="4 3"') + '/>');
        if (red) out.push('<circle cx="' + x2 + '" cy="' + y2 + '" r="4" fill="#c62828"/>');
      });
    });
    edges.innerHTML = out.join("");
  }

  function go(id){ location.hash = id; }
  function fromHash(){
    var id = decodeURIComponent(location.hash.slice(1));
    sel = N[id] ? chain(id) : [S.root];
    render();
    if (N[id] && card(id)) card(id).scrollIntoView({block: "nearest", inline: "nearest"});
  }
  document.addEventListener("click", function(ev){
    var c = ev.target.closest && ev.target.closest(".card"); if (!c) return;
    var id = c.dataset.id;
    // clicking the deepest selected card collapses it back to its parent
    go(sel[sel.length - 1] === id && N[id].parent ? N[id].parent : id);
  });
  document.addEventListener("keydown", function(ev){
    if (ev.target.tagName === "INPUT") return;
    var last = sel[sel.length - 1];
    if (ev.key === "Enter" && document.activeElement.classList.contains("card")) go(document.activeElement.dataset.id);
    else if ((ev.key === "Escape" || ev.key === "Backspace") && N[last].parent){ ev.preventDefault(); go(N[last].parent); }
    else if ((ev.key === "j" || ev.key === "J") && S.origin) go(S.origin);
    else if (ev.key === "u" || ev.key === "U"){ onlyBad = !onlyBad; render(); }
  });
  document.getElementById("jump").onclick = function(){ if (S.origin) go(S.origin); };
  window.addEventListener("hashchange", fromHash);
  window.addEventListener("resize", function(){ requestAnimationFrame(drawEdges); });
  document.getElementById("graph").addEventListener("scroll", function(){ requestAnimationFrame(drawEdges); });
  fromHash();
})();
</script>
%%REFRESH%%
</body></html>
"""
