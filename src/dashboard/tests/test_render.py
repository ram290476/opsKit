import json
import re
from html.parser import HTMLParser

from dashboard.__main__ import main
from dashboard.demo import demo_tree
from dashboard.models import Level, MetricSeries, Threshold
from dashboard.panels import evaluate_threshold
from dashboard.render import mermaid_incident, mermaid_workflow, render_html, render_text, sparkline_svg
from dashboard.triage import triage


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids, self.tags, self.external = set(), 0, []

    def handle_starttag(self, tag, attrs):
        self.tags += 1
        a = dict(attrs)
        if "id" in a:
            self.ids.add(a["id"])
        for key in ("src", "href"):
            if (a.get(key) or "").startswith(("http://", "https://", "//")):
                self.external.append(a[key])


def test_html_renders_every_node_with_detail_and_state():
    result = triage(demo_tree())
    doc = render_html(result)
    p = _Collect()
    p.feed(doc)
    for e in result.root.walk():
        assert f"node-{e.id}" in p.ids and f"detail-{e.id}" in p.ids
    assert {"node-cluster-prod-eks-usw2", "node-ctr-checkout-7d9f-x2k-checkout", "jump", "crumbs", "edges"} <= p.ids
    assert p.external == []                                     # self-contained: no CDN
    state = json.loads(re.search(r'<script id="state" type="application/json">(.*?)</script>', doc, re.S).group(1))
    assert state["origin"] == "ctr-checkout-7d9f-x2k-checkout"
    assert state["path"][0] == "cluster-prod-eks-usw2" and len(state["path"]) == 6
    assert 'class="card critical own-critical on-path origin"' in doc
    assert "ROOT CAUSE" in doc and doc.count("<svg class=\"spark\"") > 50


def test_sparkline_marks_threshold_and_onset():
    m = evaluate_threshold(Level.POD, MetricSeries("restarts", "count", [0, 0, 0, 1, 2, 3]))
    svg = sparkline_svg(m)
    assert svg.startswith("<svg") and "polyline" in svg and 'class="onset"' in svg and "stroke-dasharray" in svg
    empty = evaluate_threshold(Level.POD, MetricSeries("restarts", "count", []))
    assert "no data" in sparkline_svg(empty)
    flat = evaluate_threshold(Level.POD, MetricSeries("cpu_pct", "%", [5, 5, 5]))
    assert "polyline" in sparkline_svg(flat)                    # zero span does not divide by zero


def test_text_and_mermaid_fallbacks():
    result = triage(demo_tree())
    text = render_text(result)
    assert "ROOT CAUSE" in text and "checkout-7d9f-x2k" in text and "healthy" in text
    assert "nlb-internal-grpc" not in text                      # healthy subtree collapsed
    assert "nlb-internal-grpc" in render_text(result, show_healthy=True)
    m = mermaid_incident(result)
    assert m.startswith("stateDiagram-v2") and "class ctr_checkout_7d9f_x2k_checkout origin" in m
    assert "SeeTrend --> SpotAnomaly" in mermaid_workflow()


def test_cli_demo_writes_html_and_exits_1_on_incident(tmp_path, capsys):
    out = tmp_path / "triage.html"
    assert main(["demo", "--html", str(out)]) == 1
    assert out.read_text().startswith("<!doctype html>")
    assert "Root-cause origin" in capsys.readouterr().out


def test_threshold_override_type():
    assert Threshold(1, 2).evaluate(1.5).value == "warn"
