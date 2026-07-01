"""Render the FICC monthly report (docs/report/report-template.html) to PDF.

Python port of docs/report/generate-report.js + generate-pdf.js, using Jinja2
for placeholder substitution and Playwright (headless Chromium) for the
HTML -> PDF step, so the output matches the original Node/Puppeteer pipeline
without adding a Node.js runtime dependency.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

from web.services.artifacts import project_root

REPORT_DIR = project_root() / "docs" / "report"
TEMPLATE_NAME = "report-template.html"


def _render_kpis(kpis: list[dict[str, Any]]) -> str:
    parts = []
    for kpi in kpis:
        accent_cls = " accent" if kpi.get("accent") else ""
        value_cls = f" {kpi['valueClass']}" if kpi.get("valueClass") else ""
        value_style = ' style="font-size:12.5pt;"' if kpi.get("label") == "本月再平衡" else ""
        parts.append(
            f'<div class="kpi{accent_cls}">'
            f'<div class="label">{kpi["label"]}</div>'
            f'<div class="value{value_cls}"{value_style}>{kpi["value"]}</div>'
            f'<div class="delta">{kpi["delta"]}</div>'
            f"</div>"
        )
    return "".join(parts)


def _render_donut_circles(segments: list[dict[str, Any]]) -> str:
    """Concentric stroke-dasharray ring per segment, matching generate-report.js's example math."""
    circumference = 100.0
    radius_attrs = 'cx="21" cy="21" r="15.9" fill="transparent"'
    circles = [
        f'<circle {radius_attrs} stroke="#EDEFF3" stroke-width="6"></circle>'
    ]
    offset = 25.0  # starting rotation offset, matches the template's example
    for seg in segments:
        value = float(seg["value"])
        dashoffset = offset
        circles.append(
            f'<circle {radius_attrs} stroke="{seg["color"]}" stroke-width="6" '
            f'stroke-dasharray="{value:.1f} {circumference - value:.1f}" '
            f'stroke-dashoffset="{dashoffset:.1f}"></circle>'
        )
        offset -= value
    total = sum(float(s["value"]) for s in segments)
    circles.append(
        f'<text x="21" y="19.6" text-anchor="middle" font-size="4.6" fill="#0B2447" '
        f'font-weight="700">{total:.0f}%</text>'
    )
    circles.append(
        '<text x="21" y="24.4" text-anchor="middle" font-size="2.7" fill="#5B6B82">配置中</text>'
    )
    return "".join(circles)


def _render_allocation_legend(segments: list[dict[str, Any]]) -> str:
    parts = []
    current_group = None
    for seg in segments:
        if seg["group"] != current_group:
            current_group = seg["group"]
            group_total = sum(
                float(s["value"]) for s in segments if s["group"] == current_group
            )
            parts.append(f'<div class="grp-label">{current_group} · {group_total:.1f}%</div>')
        parts.append(
            f'<div class="row">'
            f'<span class="dot" style="background:{seg["color"]}"></span>'
            f'<span class="nm">{seg["name"]}</span>'
            f'<span class="pct">{seg["value"]}%</span>'
            f"</div>"
        )
    return "".join(parts)


def _render_allocation_change_bars(changes: list[dict[str, Any]]) -> str:
    """Horizontal diverging bars for per-asset weight change (本期变动), in percentage points."""
    parts = []
    for row in changes:
        delta = float(row["delta"])
        cls = "pos" if delta >= 0 else "neg"
        width = min(abs(delta) / max(row.get("maxAbsDelta", 1.0), 1e-6), 1.0) * 50
        parts.append(
            f'<div class="chg-row"><span class="chg-name">{row["name"]}</span>'
            f'<div class="chg-bar-track"><div class="chg-mid"></div>'
            f'<div class="chg-bar {cls}" style="width:{width:.1f}%"></div></div>'
            f'<span class="chg-val {cls}">{delta:+.1f}</span></div>'
        )
    return "".join(parts)


def _render_returns_table(groups: list[dict[str, Any]]) -> str:
    html = ('<thead><tr><th>资产</th><th class="num">期初</th><th class="num">期末</th>'
            '<th class="num">区间收益</th><th>贡献 / 方向</th></tr></thead><tbody>')
    for group in groups:
        html += f'<tr class="grp"><td colspan="5">{group["group"]}</td></tr>'
        for item in group["items"]:
            html += (
                f'<tr><td>{item["asset"]}</td>'
                f'<td class="num">{item.get("priceStart", "N/A")}</td>'
                f'<td class="num">{item.get("priceEnd", "N/A")}</td>'
                f'<td class="num {item["returnClass"]}">{item["return"]}</td>'
                f'<td class="bar-cell"><div class="bar-track"><div class="bar-mid"></div>'
                f'<div class="bar-fill {item["returnClass"]}" style="width:{item["barWidth"]}%"></div>'
                f"</div></td></tr>"
            )
    html += "</tbody>"
    return html


def _render_risk_contribution(rows: list[dict[str, Any]]) -> str:
    parts = []
    for row in rows:
        parts.append(
            f'<div class="riskbar-row"><span>{row["name"]}</span>'
            f'<div class="riskbar-track"><div class="riskbar-fill" '
            f'style="width:{row["percentage"]}%; background:{row["color"]};"></div></div>'
            f'<span>{row["percentage"]}%</span></div>'
        )
    return "".join(parts)


def _render_commentary(items: list[dict[str, Any]]) -> str:
    parts = []
    for item in items:
        parts.append(
            f'<div class="dot-item"><span class="marker">{item["marker"]}</span>'
            f'<span>{item["text"]}</span></div>'
        )
    return "".join(parts)


def _render_allocation_compact_table(segments: list[dict[str, Any]],
                                      segments_prev: list[dict[str, Any]],
                                      prev_date: str | None = None,
                                      curr_date: str | None = None) -> str:
    """Compact two-column (上期 / 本期) allocation comparison table.

    Common assets show both percentages side-by-side. Assets only in the
    previous period are shown as 'removed' (red); new assets are 'added' (green).
    """
    prev_map = {s["name"]: s for s in segments_prev}
    curr_map = {s["name"]: s for s in segments}

    # Determine ordered group structure from current period (primary) plus prev-only assets
    groups: dict[str, list[str]] = {}
    for seg in segments:
        groups.setdefault(seg["group"], []).append(seg["name"])
    for seg in segments_prev:
        if seg["name"] not in curr_map:
            groups.setdefault(seg["group"], []).append(seg["name"])

    prev_hdr = prev_date or "上期"
    curr_hdr = curr_date or "本期"
    html = ('<table class="alloc-cmp-table">'
            '<thead><tr>'
            '<th></th><th></th>'
            f'<th>{prev_hdr}</th><th>{curr_hdr}</th>'
            '</tr></thead><tbody>')

    for group, names in groups.items():
        group_total_curr = sum(float(curr_map[n]["value"]) for n in names if n in curr_map)
        html += f'<tr class="grp-row"><td colspan="4">{group} · {group_total_curr:.1f}%</td></tr>'
        for name in names:
            in_prev = name in prev_map
            in_curr = name in curr_map
            color = curr_map[name]["color"] if in_curr else prev_map[name]["color"]
            prev_val = f'{float(prev_map[name]["value"]):.1f}%' if in_prev else '—'
            curr_val = f'{float(curr_map[name]["value"]):.1f}%' if in_curr else '—'
            prev_cls = ''
            curr_cls = ''
            if in_prev and not in_curr:
                prev_cls = ' class="pct removed"'
                curr_cls = ' class="dash"'
            elif in_curr and not in_prev:
                prev_cls = ' class="dash"'
                curr_cls = ' class="pct added"'
            else:
                prev_cls = ' class="pct"'
                curr_cls = ' class="pct"'
            html += (
                f'<tr>'
                f'<td class="dot-cell"><span class="dot" style="background:{color}"></span></td>'
                f'<td class="nm">{name}</td>'
                f'<td{prev_cls}>{prev_val}</td>'
                f'<td{curr_cls}>{curr_val}</td>'
                f'</tr>'
            )

    html += '</tbody></table>'
    return html


def _render_corr_matrix_table(corr_data: dict[str, Any] | None) -> str:
    """Render a correlation matrix as a colour-coded HTML table.

    corr_data: {"labels": [...], "values": [[...]]}  — lower-triangle only (upper is mirrored).
    Diagonal cells show '1'.
    """
    if not corr_data:
        return '<div style="font-size:6.6pt;color:#5B6B82;padding:2mm;">暂无相关性数据</div>'

    labels: list[str] = corr_data.get("labels", [])
    values: list[list[float]] = corr_data.get("values", [])
    if not labels or not values:
        return '<div style="font-size:6.6pt;color:#5B6B82;padding:2mm;">暂无相关性数据</div>'

    def _cls(r: int, c: int, v: float) -> str:
        if r == c:
            return 'c-diag'
        if v >= 0.7:
            return 'c-high-pos'
        if v >= 0.3:
            return 'c-mid-pos'
        if v >= 0.1:
            return 'c-low-pos'
        if v >= -0.1:
            return 'c-zero'
        if v >= -0.3:
            return 'c-low-neg'
        return 'c-mid-neg'

    html = '<table class="corr-table"><thead><tr><th></th>'
    for lbl in labels:
        html += f'<th>{lbl}</th>'
    html += '</tr></thead><tbody>'

    for r, row_lbl in enumerate(labels):
        html += f'<tr><td>{row_lbl}</td>'
        for c, _ in enumerate(labels):
            if r == c:
                html += f'<td class="c-diag">1</td>'
            else:
                v = float(values[r][c]) if r < len(values) and c < len(values[r]) else 0.0
                css = _cls(r, c, v)
                html += f'<td class="{css}">{v:.2f}</td>'
        html += '</tr>'

    html += '</tbody></table>'
    return html


def _render_nav_chart_svg(nav_points: dict[str, Any]) -> str:
    """nav_points: {'rp': [(x,y), ...], 'net': [(x,y), ...]} in the 300x90 viewBox.
    Plots cumulative-return curves for total return (RP) and net-of-cost (net)."""
    rp_points = nav_points.get("rp", [])
    net_points = nav_points.get("net", [])

    def _fmt(points: list[tuple[float, float]]) -> str:
        return " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    parts = [
        '<polyline fill="none" stroke="#DCE3EC" stroke-width="1" points="0,75 300,75" />'
    ]
    if rp_points:
        parts.append(
            f'<polyline fill="none" stroke="#2E4D7B" stroke-width="1.6" points="{_fmt(rp_points)}" />'
        )
    if net_points:
        parts.append(
            f'<polyline fill="none" stroke="#2EC4B6" stroke-width="1.8" points="{_fmt(net_points)}" />'
        )
    if rp_points:
        x, y = rp_points[-1]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.2" fill="#2E4D7B" />')
    if net_points:
        x, y = net_points[-1]
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="#2EC4B6" />')
    return "".join(parts)


def render_report_html(report_data: dict[str, Any]) -> str:
    """Substitute report_data into report-template.html, returning the final HTML string."""
    env = Environment(loader=FileSystemLoader(str(REPORT_DIR)), autoescape=False)
    template = env.get_template(TEMPLATE_NAME)

    report = report_data["report"]
    alloc = report_data["allocation"]
    return template.render(
        reportMonth=report["reportMonth"],
        reportPeriod=report["reportPeriod"],
        publishDate=report["publishDate"],
        kpiRows=_render_kpis(report_data["kpis"]),
        allocationEffectiveDate=alloc["effectiveDate"],
        allocationCompactTable=_render_allocation_compact_table(
            alloc["segments"], alloc.get("segmentsPrev", []),
            alloc.get("prevEffectiveDate"), alloc["effectiveDate"]),
        allocationChangeBars=_render_allocation_change_bars(alloc.get("changes", [])),
        returnsTable=_render_returns_table(report_data["returns"]),
        returnsPeriod=report.get("returnsPeriod", report["reportPeriod"]),
        navChartSVG=_render_nav_chart_svg(report_data.get("navChart", {})),
        riskContribution=_render_risk_contribution(report_data["riskContribution"]),
        corrMatrixTable=_render_corr_matrix_table(report_data.get("corrMatrix")),
        commentary=_render_commentary(report_data["commentary"]),
    )


def render_report_pdf(report_data: dict[str, Any], output_path: Path) -> Path:
    """Render report_data through the template and write a PDF to output_path."""
    html = render_report_html(report_data)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="networkidle")
            page.pdf(
                path=str(output_path),
                width="297mm",
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                print_background=True,
                prefer_css_page_size=False,
            )
        finally:
            browser.close()

    return output_path
