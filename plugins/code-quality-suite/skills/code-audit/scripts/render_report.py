#!/usr/bin/env python3
"""Render a code audit findings JSON file into a self-contained HTML report.

Usage:
    python3 render_report.py <findings.json> <output.html>

Standard library only. The input format is described in
references/report-data.md next to this script's skill folder.
"""
import html
import json
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import quote

SEVERITIES = ["high", "medium", "low"]
SEVERITY_LABEL = {"high": "High", "medium": "Medium", "low": "Low"}
SEVERITY_MEANING = {
    "high": "Fix soon: risk of bugs, leaks or security problems.",
    "medium": "Plan a fix: makes the code harder to work on or trust.",
    "low": "Nice to fix: tidy-ups and small improvements.",
}
CATEGORIES = ["Standards", "Duplication", "Logging", "Security", "Testing", "Dependencies"]
CATEGORY_LABEL = {
    "Standards": "Coding Standards",
    "Duplication": "Duplicate Code",
    "Logging": "Logging & Debug Leftovers",
    "Security": "Secrets & Security",
    "Testing": "Tests",
    "Dependencies": "Dependencies",
}
CATEGORY_CHECKS = {
    "Standards": "Naming, patterns, error handling and style are consistent across the code.",
    "Duplication": "The same logic, blocks or constants are not copy-pasted in several places.",
    "Logging": "No raw console/print calls, debug leftovers or sensitive data in logs.",
    "Security": "No hardcoded secrets, unsafe env handling, .gitignore gaps or leaking errors.",
    "Testing": "Source files have meaningful tests that cover edge cases and are not fragile.",
    "Dependencies": "Packages are not outdated or vulnerable, and the lockfile is committed.",
}
EFFORTS = ["quick", "medium", "complex"]
EFFORT_LABEL = {"quick": "Quick win", "medium": "Medium effort", "complex": "Complex"}
EFFORT_TIME = {"quick": "under 30 min each", "medium": "30 min to 2 hours each", "complex": "more than 2 hours each"}
# Rough penalty per finding, used only for the headline health score.
PENALTY = {"high": 8, "medium": 3, "low": 1}


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def fail(message: str) -> None:
    sys.stderr.write(f"render_report: {message}\n")
    sys.exit(1)


def load(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as err:
        fail(f"cannot read {path}: {err}")
    findings = data.get("findings")
    if not isinstance(findings, list):
        fail("'findings' must be a list")
    for i, f in enumerate(findings, 1):
        f.setdefault("_ref", f.get("id") or f"#{i}")
        sev = str(f.get("severity", "")).lower()
        if sev not in SEVERITIES:
            fail(f"finding {f['_ref']}: severity must be one of {SEVERITIES}, got {sev!r}")
        f["severity"] = sev
        if f.get("category") not in CATEGORIES:
            fail(f"finding {f['_ref']}: category must be one of {CATEGORIES}, got {f.get('category')!r}")
        eff = str(f.get("effort", "medium")).lower()
        f["effort"] = eff if eff in EFFORTS else "medium"
        if not f.get("title"):
            fail(f"finding {f['_ref']}: missing 'title'")
        f.setdefault("locations", [])
    # Number findings in report order when the data did not supply ids.
    if not all(f.get("id") for f in findings):
        order = {s: i for i, s in enumerate(SEVERITIES)}
        ranked = sorted(findings, key=lambda f: (order[f["severity"]], CATEGORIES.index(f["category"])))
        for i, f in enumerate(ranked, 1):
            f["id"] = f"F{i}"
    return data


def health(findings: list) -> tuple:
    score = max(0, 100 - sum(PENALTY[f["severity"]] for f in findings))
    for limit, grade, word in [(90, "A", "Healthy"), (75, "B", "Good"), (60, "C", "Needs attention"),
                               (40, "D", "Poor"), (0, "F", "Critical")]:
        if score >= limit:
            return score, grade, word
    return score, "F", "Critical"


def location_html(loc: dict, root: str, short: bool = False) -> str:
    path = loc.get("path", "")
    line = loc.get("line")
    full_text = f"{path}:{line}" if line else path
    # Tables only have room for the file name; the full path stays in the tooltip.
    text = full_text.rsplit("/", 1)[-1] if short else full_text
    if root and path and not path.startswith(("http://", "https://")):
        full = path if path.startswith("/") else f"{root.rstrip('/')}/{path}"
        href = "vscode://file" + quote(full) + (f":{line}" if line else "")
        return f'<a class="loc" href="{esc(href)}" title="{esc(full_text)} (open in VS Code)">{esc(text)}</a>'
    return f'<span class="loc" title="{esc(full_text)}">{esc(text)}</span>'


def finding_card(f: dict, root: str) -> str:
    locs = "".join(location_html(loc, root) for loc in f["locations"])
    if f.get("package"):
        locs += f'<span class="loc">{esc(f["package"])}</span>'
    also = ""
    if f.get("also_flagged_by"):
        also = '<span class="tag">Also found by: ' + esc(", ".join(f["also_flagged_by"])) + "</span>"
    rows = ""
    for key, label in [("what", "What we found"), ("why", "Why it matters"), ("fix", "How to fix")]:
        if f.get(key):
            rows += f'<div class="row"><div class="row-label">{label}</div><div>{esc(f[key])}</div></div>'
    return f"""
<article class="card sev-{f['severity']}" data-sev="{f['severity']}" data-cat="{esc(f['category'])}">
  <header>
    <span class="badge {f['severity']}">{SEVERITY_LABEL[f['severity']]}</span>
    <span class="fid">{esc(f['id'])}</span>
    <h4>{esc(f['title'])}</h4>
  </header>
  {rows}
  <div class="locs">{locs or '<span class="muted">No specific file</span>'}</div>
  <footer><span class="tag effort-{f['effort']}">{EFFORT_LABEL[f['effort']]}</span>{also}</footer>
</article>"""


def build_live_site(ls: dict) -> str:
    """Render a plain-language 'Live site check' section, or '' when absent."""
    if not ls:
        return ""
    site = esc(ls.get("site", ""))
    intro = esc(ls.get("intro", ""))

    # What we looked at: one readable line per URL.
    target_rows = ""
    for t in ls.get("targets", []):
        bits = []
        if t.get("status"):
            bits.append(f"responded {esc(str(t['status']))}")
        if t.get("tls"):
            bits.append(esc(t["tls"]))
        if t.get("cert"):
            bits.append("certificate " + esc(t["cert"]))
        if t.get("note"):
            bits.append(esc(t["note"]))
        target_rows += (f'<tr><td class="loc" style="border:0">{esc(t.get("url", ""))}</td>'
                        f'<td style="border-bottom:1px solid var(--line)">{" · ".join(bits)}</td></tr>')
    targets_block = (f'<table class="ls-targets"><tbody>{target_rows}</tbody></table>'
                     if target_rows else "")

    good = "".join(f"<li>{esc(g)}</li>" for g in ls.get("good", []))
    issues = "".join(f"<li>{esc(i)}</li>" for i in ls.get("issues", []))
    good_block = (f'<div class="ls-col ls-good"><h3>Working well</h3><ul>{good}</ul></div>'
                  if good else "")
    issues_block = (f'<div class="ls-col ls-issue"><h3>Needs attention</h3><ul>{issues}</ul></div>'
                    if issues else '<div class="ls-col ls-good"><h3>Needs attention</h3>'
                    '<p class="muted">Nothing flagged.</p></div>')

    return f"""
<section class="live-site">
  <h2>Live site check</h2>
  <p>We also looked at the running site, {site}, from the outside, the way a visitor's browser sees it. This was a safe, look-only check: one normal page request per address, with no attempts to break in. {intro}</p>
  {targets_block}
  <div class="ls-cols">{good_block}{issues_block}</div>
  <p class="muted small">The matching issues also appear as cards in "All findings" below.</p>
</section>"""


def render(data: dict) -> str:
    findings = data["findings"]
    root = data.get("root", "")
    sev_count = Counter(f["severity"] for f in findings)
    cat_count = {c: Counter(f["severity"] for f in findings if f["category"] == c) for c in CATEGORIES}
    score, grade, word = health(findings)
    total = len(findings)
    order = {s: i for i, s in enumerate(SEVERITIES)}
    findings_sorted = sorted(findings, key=lambda f: (order[f["severity"]], CATEGORIES.index(f["category"])))

    # Severity distribution bar.
    dist = ""
    for s in SEVERITIES:
        if sev_count[s]:
            dist += f'<div class="seg {s}" style="flex:{sev_count[s]}" title="{SEVERITY_LABEL[s]}: {sev_count[s]}">{sev_count[s]}</div>'
    if not dist:
        dist = '<div class="seg none" style="flex:1">No findings</div>'

    # Category table.
    biggest = max([sum(c.values()) for c in cat_count.values()] + [1])
    cat_rows = ""
    for c in CATEGORIES:
        cc = cat_count[c]
        n = sum(cc.values())
        bar = "".join(
            f'<span class="mini {s}" style="width:{cc[s] / biggest * 100:.1f}%"></span>' for s in SEVERITIES if cc[s]
        )
        status = '<span class="ok">Clean</span>' if n == 0 else f"{n} issue{'s' if n != 1 else ''}"
        cat_rows += f"""<tr><td><strong>{CATEGORY_LABEL[c]}</strong><div class="muted small">{CATEGORY_CHECKS[c]}</div></td>
<td class="num high-t">{cc['high'] or '–'}</td><td class="num medium-t">{cc['medium'] or '–'}</td>
<td class="num low-t">{cc['low'] or '–'}</td><td class="barcell"><div class="minibar">{bar}</div><span class="small">{status}</span></td></tr>"""

    # Top priorities.
    top = [f for f in findings_sorted if f["severity"] == "high"][:5]
    top_html = "".join(
        f'<li><span class="badge high">High</span> <strong>{esc(f["title"])}</strong>'
        f'<span class="muted small"> · {CATEGORY_LABEL[f["category"]]} · {esc(f["id"])}</span></li>'
        for f in top
    ) or '<li class="muted">No high-priority issues. Nice work.</li>'

    # Findings grouped by category.
    groups = ""
    for c in CATEGORIES:
        items = [f for f in findings_sorted if f["category"] == c]
        if items:
            groups += f'<div class="group" data-cat="{c}"><h3>{CATEGORY_LABEL[c]} <span class="count">{len(items)}</span></h3>'
            groups += "".join(finding_card(f, root) for f in items) + "</div>"

    # Implementation plan.
    plan = ""
    for e in EFFORTS:
        items = [f for f in findings_sorted if f["effort"] == e]
        if not items:
            continue
        rows = "".join(
            f'<tr><td class="fid">{esc(f["id"])}</td><td><span class="badge {f["severity"]}">{SEVERITY_LABEL[f["severity"]]}</span></td>'
            f'<td>{esc(f["title"])}</td>'
            f'<td>{"<br>".join(location_html(loc, root, short=True) for loc in f["locations"][:3]) or esc(f.get("package", "–"))}</td>'
            f'<td>{esc(f.get("fix", ""))}</td></tr>'
            for f in items
        )
        plan += f"""<div class="plan-block"><h3><span class="tag effort-{e}">{EFFORT_LABEL[e]}</span>
<span class="muted small">{EFFORT_TIME[e]} · {len(items)} item{'s' if len(items) != 1 else ''}</span></h3>
<table class="plan"><thead><tr><th>#</th><th>Severity</th><th>Issue</th><th>Where</th><th>Fix</th></tr></thead><tbody>{rows}</tbody></table></div>"""

    fix_order = "".join(
        f"<li><strong>{esc(s.get('step', ''))}</strong>{(' – ' + esc(s['why'])) if s.get('why') else ''}</li>"
        if isinstance(s, dict) else f"<li>{esc(s)}</li>"
        for s in data.get("fix_order", [])
    )
    checks = "".join(f'<li><span class="box"></span>{esc(v)}</li>' for v in data.get("verification", []))
    notes = "".join(f"<li>{esc(n)}</li>" for n in data.get("tool_notes", []))
    filters = "".join(
        f'<button class="chip {s}" data-filter-sev="{s}">{SEVERITY_LABEL[s]} ({sev_count[s]})</button>' for s in SEVERITIES
    )
    legend = "".join(
        f'<div><span class="badge {s}">{SEVERITY_LABEL[s]}</span> {SEVERITY_MEANING[s]}</div>' for s in SEVERITIES
    )
    live_site_html = build_live_site(data.get("live_site"))
    report_date = data.get("date") or date.today().isoformat()
    title = f"Code Audit Report – {data.get('project_name', 'Project')}"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{CSS}</style></head>
<body>
<div class="page">
<header class="cover">
  <div>
    <div class="eyebrow">Code Quality Audit</div>
    <h1>{esc(data.get('project_name', 'Project'))}</h1>
    <div class="meta">
      <span><b>Scope:</b> {esc(data.get('scope', 'Full project'))}</span>
      <span><b>Date:</b> {esc(report_date)}</span>
      <span><b>Stack:</b> {esc(data.get('project', ''))}</span>
    </div>
  </div>
  <div class="cover-side">
    <div class="score grade-{grade}"><div class="score-num">{score}</div><div class="score-grade">Grade {grade}</div><div class="score-word">{word}</div></div>
    <button type="button" class="pdf-btn no-print" onclick="window.print()" title="Opens the print dialog; choose 'Save as PDF' as the destination">&#8681; Download PDF</button>
  </div>
</header>

<section class="summary">
  <h2>Summary</h2>
  <p class="lead">{esc(data.get('summary', ''))}</p>
  <div class="cards">
    <div class="stat"><div class="stat-num">{total}</div><div class="stat-label">Total issues</div></div>
    <div class="stat high"><div class="stat-num">{sev_count['high']}</div><div class="stat-label">High</div></div>
    <div class="stat medium"><div class="stat-num">{sev_count['medium']}</div><div class="stat-label">Medium</div></div>
    <div class="stat low"><div class="stat-num">{sev_count['low']}</div><div class="stat-label">Low</div></div>
  </div>
  <div class="dist">{dist}</div>
  <div class="legend">{legend}</div>
</section>

<section>
  <h2>Fix these first</h2>
  <ol class="top">{top_html}</ol>
</section>

{live_site_html}
<section>
  <h2>Results by area</h2>
  <table class="cats"><thead><tr><th>Area checked</th><th class="num">High</th><th class="num">Medium</th><th class="num">Low</th><th>Overview</th></tr></thead>
  <tbody>{cat_rows}</tbody></table>
</section>

<section>
  <h2>All findings</h2>
  <div class="filters no-print"><button class="chip active" data-filter-sev="all">All ({total})</button>{filters}</div>
  {groups or '<p class="muted">No issues were found in this scope.</p>'}
</section>

<section>
  <h2>Implementation plan</h2>
  {plan or '<p class="muted">Nothing to fix.</p>'}
  {f'<h3>Suggested fix order</h3><ol class="order">{fix_order}</ol>' if fix_order else ''}
  {f'<h3>Verification checklist</h3><ul class="checks">{checks}</ul>' if checks else ''}
</section>

<section class="appendix">
  <h2>How this audit was done</h2>
  <p>Six automated reviewers each checked one area of the code in parallel. Their results were merged, duplicates removed, and each issue rated by severity and effort.
  The health score starts at 100 and subtracts {PENALTY['high']} per high, {PENALTY['medium']} per medium and {PENALTY['low']} per low issue. It is a rough guide, not an exact measure.</p>
  {f'<h3>Tool notes</h3><ul>{notes}</ul>' if notes else ''}
  <p class="muted small">File links open in VS Code. Findings come from automated analysis and should be confirmed before large changes.</p>
</section>
<footer class="foot">Generated {esc(report_date)} · code-audit</footer>
</div>
<script>{JS}</script>
</body></html>"""


CSS = """
:root{--ink:#1f2937;--muted:#6b7280;--line:#e5e7eb;--bg:#f6f7f9;--card:#fff;--accent:#3949ab;
--high:#c62828;--high-bg:#fdecea;--medium:#a15c00;--medium-bg:#fff4e0;--low:#1565c0;--low-bg:#e8f1fc;--ok:#2e7d32}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.page{max-width:1100px;margin:0 auto;padding:32px 24px 48px}
h1{font-size:30px;margin:4px 0 10px}h2{font-size:21px;margin:0 0 14px;padding-bottom:8px;border-bottom:2px solid var(--line)}
h3{font-size:16px;margin:22px 0 10px}h4{margin:0;font-size:15px}
section{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:22px 24px;margin:18px 0}
.cover{display:flex;justify-content:space-between;align-items:center;gap:24px;background:linear-gradient(135deg,#283593,#3949ab 60%,#5c6bc0);color:#fff;border-radius:14px;padding:28px 32px}
.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:12px;opacity:.85}
.meta{display:flex;flex-wrap:wrap;gap:6px 20px;font-size:13px;opacity:.95}
.score{background:#fff;color:var(--ink);border-radius:12px;padding:14px 22px;text-align:center;min-width:140px}
.score-num{font-size:40px;font-weight:700;line-height:1}.score-grade{font-weight:600;margin-top:4px}.score-word{font-size:12px;color:var(--muted)}
.grade-A .score-num,.grade-B .score-num{color:var(--ok)}.grade-C .score-num{color:var(--medium)}.grade-D .score-num,.grade-F .score-num{color:var(--high)}
.cover-side{display:flex;flex-direction:column;align-items:stretch;gap:10px}
.pdf-btn{background:rgba(255,255,255,.15);color:#fff;border:1px solid rgba(255,255,255,.6);border-radius:8px;padding:8px 14px;font-size:13px;font-weight:600;cursor:pointer}
.pdf-btn:hover{background:rgba(255,255,255,.28)}
.lead{font-size:16px;margin:0 0 16px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.stat{border:1px solid var(--line);border-radius:10px;padding:14px;text-align:center}
.stat-num{font-size:28px;font-weight:700}.stat-label{font-size:13px;color:var(--muted)}
.stat.high{background:var(--high-bg)}.stat.high .stat-num{color:var(--high)}
.stat.medium{background:var(--medium-bg)}.stat.medium .stat-num{color:var(--medium)}
.stat.low{background:var(--low-bg)}.stat.low .stat-num{color:var(--low)}
.dist{display:flex;height:26px;border-radius:7px;overflow:hidden;margin:16px 0 12px;gap:2px}
.seg{color:#fff;font-size:12px;font-weight:600;display:flex;align-items:center;justify-content:center;min-width:26px}
.seg.high{background:var(--high)}.seg.medium{background:var(--medium)}.seg.low{background:var(--low)}.seg.none{background:var(--ok)}
.legend{display:grid;gap:6px;font-size:13px;color:var(--muted)}
.badge{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;padding:2px 8px;border-radius:999px;white-space:nowrap}
.badge.high{background:var(--high-bg);color:var(--high);border:1px solid var(--high)}
.badge.medium{background:var(--medium-bg);color:var(--medium);border:1px solid var(--medium)}
.badge.low{background:var(--low-bg);color:var(--low);border:1px solid var(--low)}
.top{margin:0;padding-left:22px}.top li{margin:6px 0}
table{width:100%;border-collapse:collapse;font-size:14px}
th{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);border-bottom:2px solid var(--line);padding:8px}
td{border-bottom:1px solid var(--line);padding:10px 8px;vertical-align:top}
.num{text-align:center;width:70px;font-weight:700}.high-t{color:var(--high)}.medium-t{color:var(--medium)}.low-t{color:var(--low)}
.barcell{width:220px}.minibar{display:flex;height:8px;background:var(--bg);border-radius:4px;overflow:hidden;margin:6px 0 4px}
.mini.high{background:var(--high)}.mini.medium{background:var(--medium)}.mini.low{background:var(--low)}
.ok{color:var(--ok);font-weight:600}.muted{color:var(--muted)}.small{font-size:12px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:6px}
.chip{border:1px solid var(--line);background:#fff;border-radius:999px;padding:5px 14px;font-size:13px;cursor:pointer}
.chip.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.group h3 .count{background:var(--bg);border-radius:999px;padding:1px 9px;font-size:12px;color:var(--muted)}
.card{border:1px solid var(--line);border-left:5px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0;break-inside:avoid}
.card.sev-high{border-left-color:var(--high)}.card.sev-medium{border-left-color:var(--medium)}.card.sev-low{border-left-color:var(--low)}
.card header{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.fid{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:var(--muted)}
.row{display:grid;grid-template-columns:130px 1fr;gap:10px;margin:4px 0;font-size:14px}
.row-label{color:var(--muted);font-weight:600;font-size:13px}
.locs{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.loc{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;background:#f1f3f9;border:1px solid #dfe3ee;border-radius:6px;padding:2px 8px;color:#283593;text-decoration:none;word-break:break-all}
a.loc:hover{background:#e3e7f6}
.card footer{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.tag{font-size:12px;border-radius:6px;padding:2px 8px;background:var(--bg);color:var(--muted)}
.effort-quick{background:#e8f5e9;color:var(--ok)}.effort-medium{background:#fff4e0;color:var(--medium)}.effort-complex{background:#fdecea;color:var(--high)}
.plan-block h3{display:flex;align-items:center;gap:10px}
.plan td:nth-child(4){width:1%;white-space:nowrap}.plan .loc{display:inline-block;margin:2px 0;white-space:nowrap;word-break:normal}
.order li,.checks li{margin:6px 0}.checks{list-style:none;padding:0}
.box{display:inline-block;width:14px;height:14px;border:2px solid var(--muted);border-radius:3px;margin-right:10px;vertical-align:-2px}
.appendix p{font-size:14px}
.ls-targets{width:100%;border-collapse:collapse;font-size:14px;margin:4px 0 16px}
.ls-targets td{padding:8px 10px;vertical-align:top}
.ls-targets td:first-child{white-space:nowrap;color:#283593;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
.ls-cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.ls-col{border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.ls-col h3{margin:0 0 8px}.ls-col ul{margin:0;padding-left:20px}.ls-col li{margin:5px 0}
.ls-good{background:#f1f9f2;border-color:#cfe8d4}.ls-good h3{color:var(--ok)}
.ls-issue{background:var(--high-bg);border-color:#f3c9c4}.ls-issue h3{color:var(--high)}
.foot{text-align:center;color:var(--muted);font-size:12px;margin-top:24px}
.hidden{display:none}
@media (max-width:720px){.cover{flex-direction:column;align-items:flex-start}.cards{grid-template-columns:repeat(2,1fr)}.row{grid-template-columns:1fr}.ls-cols{grid-template-columns:1fr}}
@media print{body{background:#fff;font-size:12px}.page{padding:0}.no-print{display:none}section{break-inside:auto;border:none;padding:10px 0}
.cover{-webkit-print-color-adjust:exact;print-color-adjust:exact}.hidden{display:block}*{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""

JS = """
document.querySelectorAll('[data-filter-sev]').forEach(function(btn){
  btn.addEventListener('click', function(){
    var sev = btn.getAttribute('data-filter-sev');
    document.querySelectorAll('[data-filter-sev]').forEach(function(b){ b.classList.toggle('active', b === btn); });
    document.querySelectorAll('.card').forEach(function(c){ c.classList.toggle('hidden', sev !== 'all' && c.dataset.sev !== sev); });
    document.querySelectorAll('.group').forEach(function(g){
      g.classList.toggle('hidden', !g.querySelector('.card:not(.hidden)'));
    });
  });
});
"""


def main() -> None:
    if len(sys.argv) != 3:
        fail("usage: render_report.py <findings.json> <output.html>")
    data = load(sys.argv[1])
    out = Path(sys.argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(data), encoding="utf-8")
    print(out.resolve())


if __name__ == "__main__":
    main()
