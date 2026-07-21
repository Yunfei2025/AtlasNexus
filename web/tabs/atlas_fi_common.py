"""Small shared UI helpers used across the FI dashboard tab modules
(`atlas_fi_spreads.py`, `atlas_fi_curves.py`, `atlas_fi_pairs.py`).
"""

from __future__ import annotations

from dash import html


def _fi_card_header(title: str, badge_text: str | None = None) -> html.Div:
    """Card header row — title + optional meta badge. Matches the Alpha Book card pattern."""
    children_left = [
        html.Span(title, style={'fontSize': '13px', 'fontWeight': '600', 'color': 'var(--text-primary)'}),
    ]
    if badge_text:
        children_left.append(html.Span(badge_text, style={
            'fontSize': '9px', 'color': 'var(--text-muted)', 'background': 'var(--surface-input)',
            'padding': '2px 7px', 'borderRadius': '3px', 'border': '1px solid var(--border-default)',
        }))
    return html.Div(
        children_left,
        style={'display': 'flex', 'alignItems': 'center', 'gap': '10px',
               'padding': '11px 16px', 'background': 'var(--surface-panel)',
               'borderBottom': '1px solid var(--border-strong)'},
    )
