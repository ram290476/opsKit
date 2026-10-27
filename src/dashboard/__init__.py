"""dashboard - visual, interactive Kubernetes triage for EKS (incl. Fargate) and ECS Fargate.

Flow: see the trend -> spot the anomaly -> drill to the source, across six levels
Cluster > Load balancers > Network > Nodes > Pods > Containers.

    from dashboard import demo_tree, triage, render_html
    result = triage(demo_tree())
    open("triage.html", "w").write(render_html(result))

Core is stdlib only; collectors take injected boto3 / kubernetes / requests clients.
"""
from .demo import demo_tree
from .models import Entity, Health, Level, MetricSeries, Threshold, TriageResult
from .render import mermaid_incident, mermaid_workflow, render_html, render_text
from .triage import evaluate_tree, find_origin, triage

__version__ = "0.1.0"
__all__ = ["Entity", "Health", "Level", "MetricSeries", "Threshold", "TriageResult", "demo_tree",
           "evaluate_tree", "find_origin", "mermaid_incident", "mermaid_workflow", "render_html",
           "render_text", "triage"]
