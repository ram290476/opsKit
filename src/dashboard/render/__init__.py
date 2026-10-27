"""Renderers: terminal text (fallback), self-contained interactive HTML, and Mermaid."""
from .html import render_html, sparkline_svg
from .mermaid import mermaid_incident, mermaid_workflow
from .text import render_text

__all__ = ["mermaid_incident", "mermaid_workflow", "render_html", "render_text", "sparkline_svg"]
