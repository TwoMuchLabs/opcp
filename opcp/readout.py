"""The pilot readout pack: one printable view for the sponsor's decision meeting.

The scorecard report explains each process in depth. The readout answers the sponsor's questions on
a few pages: where do we stand across all critical processes, which contract renewals are our
leverage and by when must we act, and which decisions do we need to take.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from ._io import load_document
from .registers import _assessment
from .scorecard import LABEL, LOCKED, ORDER, PARTIAL, READY, Result, _badge, _e, evaluate, evaluate_answers

MEASURES = (("logic", "Logic"), ("context", "Context"), ("authority", "Authority"), ("debt", "Lock-in"),
            ("contract", "Contract"), ("swap", "Time-to-swap"), ("fallback", "Fallback"))
HORIZON_DAYS = 548  # about 18 months: renewals inside this window are the near-term leverage

_CSS = """
:root{--ink:#1d1d1b;--muted:#5f5f5a;--line:#dedcd6;--card:#fff;--bg:#f7f7f5;--accent:#2952cc;
--ready:#1f7a4d;--ready-bg:#e6f3ec;--partial:#8a5a00;--partial-bg:#fbf0d9;--locked:#b42318;--locked-bg:#fde8e6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:1000px;margin:0 auto;padding:28px 16px 40px}h1{font-size:26px;margin:0 0 2px;letter-spacing:-.01em}
h2{font-size:17px;margin:28px 0 10px}.muted{color:var(--muted)}.small{font-size:12.5px}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.tile .n{font-size:26px;font-weight:650;line-height:1.15}.tile .l{font-size:12.5px;color:var(--muted)}
.headline{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:12px 14px;margin-top:10px}
table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:13px}
th{font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600;background:#fbfbf9}
tr:last-child td{border-bottom:none}
td.c{text-align:center}.cell{display:inline-block;min-width:64px;text-align:center;border-radius:6px;padding:2px 6px;font-size:12px;font-weight:600}
.cell.ready{color:var(--ready);background:var(--ready-bg)}.cell.partial{color:var(--partial);background:var(--partial-bg)}.cell.locked{color:var(--locked);background:var(--locked-bg)}
.badge{display:inline-block;font-size:12px;font-weight:650;border-radius:999px;padding:2px 10px;white-space:nowrap}
.badge.ready{color:var(--ready);background:var(--ready-bg)}.badge.partial{color:var(--partial);background:var(--partial-bg)}.badge.locked{color:var(--locked);background:var(--locked-bg)}
.late{color:var(--locked);font-weight:600}.soon{color:var(--partial);font-weight:600}
ol.dec{margin:0;padding-left:20px}ol.dec li{margin:0 0 10px}ol.dec .why{color:var(--muted);font-size:12.5px}
.status{font-size:12.5px;color:var(--muted);margin-top:8px}footer{margin-top:28px;font-size:12px;color:var(--muted)}
.page{break-after:page}
@media print{@page{size:A4;margin:14mm}body{background:#fff;font-size:12.5px}main{padding:0;max-width:none}
.tile,.headline,table{border-color:#ccc}h2{break-after:avoid}tr{break-inside:avoid}}
@media (max-width:640px){.tiles{grid-template-columns:repeat(2,1fr)}.wide{display:block;overflow-x:auto}}
"""


def _date(value: Any) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def renewals(assessment: Mapping[str, Any], result: Result, today: dt.date) -> list[dict[str, Any]]:
    """Contracts ending within the horizon, with the last day to give notice and the gaps to close."""
    by_id = {p.id: p for p in result.critical}
    rows = []
    for proc in assessment["processes"]:
        pr = by_id.get(proc["id"])
        contract = proc.get("contract") or {}
        end = _date(contract.get("end_date"))
        if pr is None or end is None:
            continue
        days_left = (end - today).days
        if days_left > HORIZON_DAYS:
            continue
        notice = contract.get("notice_days")
        notice_by = end - dt.timedelta(days=notice) if isinstance(notice, int) else None
        gaps = next((m.finding for m in pr.measures if m.key == "contract" and m.rating != READY), "")
        rows.append({"process": pr.name, "supplier": pr.supplier, "end": end, "days_left": days_left,
                     "notice_by": notice_by, "notice_days": notice, "rating": pr.rating, "gaps": gaps})
    return sorted(rows, key=lambda r: (r["notice_by"] or r["end"]))


def decisions(assessment: Mapping[str, Any], result: Result, today: dt.date) -> list[dict[str, str]]:
    """The few decisions a sponsor can take now, most urgent first."""
    out: list[dict[str, str]] = []
    for r in renewals(assessment, result, today):
        if r["rating"] == READY and not r["gaps"]:
            continue
        when = r["notice_by"] or r["end"]
        if when < today:
            timing = f"the notice date ({when.isoformat()}) has passed: negotiate the gaps into the renewal itself"
        else:
            timing = f"decide before {when.isoformat()}, the last day to give notice"
        out.append({"what": f"Use the {r['supplier']} renewal for {r['process']} to close the exit gaps",
                    "why": f"{r['gaps'] or 'The process is ' + LABEL[r['rating']].lower() + '.'} The contract ends {r['end'].isoformat()}; {timing}.",
                    "owner": "Procurement with the process owner"})
    for c in result.concentration:
        if c.over_limit:
            out.append({"what": f"Qualify a second supplier to reduce reliance on {c.supplier}",
                        "why": f"{c.supplier} is primary for {c.share:.0%} of critical processes ({', '.join(c.processes)}), "
                               f"above the {result.settings['concentration_limit']:.0%} limit.",
                        "owner": "Third-party risk with procurement"})
    held = [p for p in result.critical if any(m.key == "logic" and m.rating == LOCKED for m in p.measures)]
    if held:
        out.append({"what": "Bring the rules of " + ", ".join(p.name for p in held) + " back under the firm's control",
                    "why": "Their rules and thresholds live in the supplier's configuration, so a replacement would have to rediscover them.",
                    "owner": "Process owner with technology"})
    estimated = [p for p in result.critical if p.swap.get("confidence") != "proven"]
    if estimated:
        worst = max(estimated, key=lambda p: (ORDER[p.rating], p.swap["total_days"]))
        out.append({"what": f"Rehearse a swap for {len(estimated)} process{'es' if len(estimated) > 1 else ''} whose time-to-swap is only estimated",
                    "why": f"Start with {worst.name}: estimated {worst.swap['total_days']} days against a {worst.swap['tolerance_days']}-day tolerance. "
                           "A shadow drill (docs/SWAP-DRILL.md) turns the estimate into evidence.",
                    "owner": "Technology with risk"})
    return out


def _evidence_share(result: Result) -> float | None:
    values = [p.evidence_coverage for p in result.critical if p.evidence_coverage is not None]
    return sum(values) / len(values) if values else None


def render_html(doc: Mapping[str, Any], today: dt.date | None = None) -> str:
    assessment = _assessment(doc)
    result = evaluate_answers(doc) if "answers_version" in doc else evaluate(assessment)
    today = today or _date(result.assessment_date) or dt.date.today()
    crit = result.critical
    counts = result.counts()

    evidence = _evidence_share(result)
    proven = sum(1 for p in crit if p.swap.get("confidence") == "proven")
    top = max(result.concentration, key=lambda c: c.share, default=None)
    limit = result.settings["concentration_limit"]
    tiles = [
        (f'{counts[LOCKED]} · {counts[PARTIAL]} · {counts[READY]}', "Locked · Partial · Ready critical processes"),
        (f"{evidence:.0%}" if evidence is not None else "n/a", "of answers backed by a record or a test"),
        (f"{proven} of {len(crit)}", "time-to-swap figures proven by a drill"),
        (f"{top.share:.0%}" if top else "n/a", f"largest supplier share ({_e(top.supplier) if top else 'none'}), limit {limit:.0%}"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="n">{n}</div><div class="l">{l}</div></div>' for n, l in tiles)
    worst = max(crit, key=lambda p: (ORDER[p.rating], p.swap["total_days"]), default=None)
    headline = ""
    if worst is not None:
        headline = (f'<div class="headline"><strong>Weakest link:</strong> {_e(worst.name)} ({_e(worst.supplier)}) is '
                    f'<strong>{LABEL[worst.rating].lower()}</strong>; replacing its supplier would take an '
                    f'{_e(worst.swap["confidence"])} {worst.swap["total_days"]} days against a {worst.swap["tolerance_days"]}-day tolerance.</div>')

    head = "".join(f"<th class='c'>{n}</th>" for _, n in MEASURES)
    grid_rows = []
    for p in sorted(crit, key=lambda p: (-ORDER[p.rating], p.name)):
        ratings = {m.key: m.rating for m in p.measures}
        cells = "".join(f"<td class='c'><span class='cell {ratings[k]}'>{LABEL[ratings[k]]}</span></td>" if k in ratings
                        else "<td class='c muted'>–</td>" for k, _ in MEASURES)
        swap = f"{p.swap['total_days']} d <span class='muted'>({_e(p.swap['confidence'])})</span>"
        grid_rows.append(f"<tr><td><strong>{_e(p.name)}</strong><br><span class='muted small'>{_e(p.supplier)}</span></td>"
                         f"{cells}<td>{swap}</td><td>{_badge(p.rating)}</td></tr>")
    grid = (f"<div class='wide'><table><thead><tr><th>Process</th>{head}<th>Swap</th><th>Overall</th></tr></thead>"
            f"<tbody>{''.join(grid_rows) or '<tr><td colspan=10>No critical processes assessed.</td></tr>'}</tbody></table></div>")

    ren_rows = []
    for r in renewals(assessment, result, today):
        nb = r["notice_by"]
        if nb is None:
            nb_html = "<span class='muted'>notice period not given</span>"
        elif nb < today:
            nb_html = f"<span class='late'>{nb.isoformat()} (passed)</span>"
        elif (nb - today).days <= 90:
            nb_html = f"<span class='soon'>{nb.isoformat()} ({(nb - today).days} days)</span>"
        else:
            nb_html = f"{nb.isoformat()} ({(nb - today).days} days)"
        ren_rows.append(f"<tr><td><strong>{_e(r['process'])}</strong><br><span class='muted small'>{_e(r['supplier'])}</span></td>"
                        f"<td>{r['end'].isoformat()}</td><td>{nb_html}</td><td>{_e(r['gaps'] or 'No contract gaps.')}</td></tr>")
    renewals_html = (f"<table><thead><tr><th>Process</th><th>Contract ends</th><th>Last day to give notice</th>"
                     f"<th>Gaps to close at renewal</th></tr></thead><tbody>{''.join(ren_rows)}</tbody></table>"
                     if ren_rows else "<p class='muted'>No contract for a critical process ends in the next 18 months, "
                                      "or no end dates were given.</p>")

    decs = decisions(assessment, result, today)
    dec_html = ("<ol class='dec'>" + "".join(
        f"<li><strong>{_e(d['what'])}.</strong><div class='why'>{_e(d['why'])} <em>Suggested owner: {_e(d['owner'])}.</em></div></li>"
        for d in decs) + "</ol>") if decs else "<p class='muted'>No decisions needed: every critical process is ready.</p>"

    so = result.signoff or {}

    def person(d: Mapping[str, Any]) -> str:
        return ", ".join(x for x in (d.get("name"), d.get("role")) if x) + (f" on {d['date']}" if d.get("date") else "")

    status = (f"Self-assessment against the {_e(result.method)}. Not a certification. "
              + (f"Prepared by {_e(person(so['prepared_by']))}. " if so.get("prepared_by") else "")
              + (f"Reviewed by {_e(person(so['reviewed_by']))}." if so.get("reviewed_by") else "<strong>Not independently reviewed.</strong>"))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Exit-readiness readout · {_e(result.organisation)}</title><style>{_CSS}</style></head><body><main>
<section class="page">
<div class="small muted">Exit-readiness readout</div><h1>{_e(result.organisation)}</h1>
<div class="muted">{_e(result.assessment_date)} · {len(crit)} critical process{'es' if len(crit) != 1 else ''}</div>
<p class="status">{status}</p>
<div class="tiles">{tiles_html}</div>{headline}
<h2>Where each process stands</h2>{grid}
<p class="small muted">Each process is rated by its weakest measure, because an exit fails at its weakest point. The full scorecard report explains every rating.</p>
</section>
<section>
<h2>Decisions for the sponsor</h2>{dec_html}
<h2>Renewals: the leverage window</h2>
<p class="small muted">Contracts ending in the next 18 months. The last day to give notice is the end date minus the notice period: after it, the firm's leverage at renewal falls.</p>
{renewals_html}
</section>
<footer>Generated locally by OPCP {__version__}. No data left this machine. Open Process Control Plane specification, section 12.
Suggested owners and decisions are prompts for discussion, not advice.</footer>
</main></body></html>"""


def readout_file(path: str | Path) -> str:
    return render_html(load_document(path))
