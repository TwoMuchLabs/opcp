"""Exit-Readiness Scorecard (spec section 12).

Turns an assessment file into ratings, actions and a one-page HTML report.
Runs entirely offline: nothing here opens a network connection.
"""

from __future__ import annotations

import datetime as dt
import html
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import __version__
from ._io import ValidationFailed, errors, load_document, schema_validator

READY, PARTIAL, LOCKED = "ready", "partial", "locked"
ORDER = {READY: 0, PARTIAL: 1, LOCKED: 2}
LABEL = {READY: "Ready", PARTIAL: "Partial", LOCKED: "Locked"}
EVIDENCE_LABEL = {"declared": "Declared", "documented": "Documented", "tested": "Tested"}

DEFAULTS = {"swap_tolerance_days": 90, "notice_tolerance_days": 90, "concentration_limit": 0.5, "lock_in_debt_partial_max": 3}


@dataclass
class Measure:
    key: str
    name: str
    finding: str
    rating: str
    action: str | None = None
    evidence: str | None = None  # declared | documented | tested, from an answers file
    refs: list[dict[str, str]] = field(default_factory=list)  # framework references for this measure


@dataclass
class ProcessResult:
    id: str
    name: str
    owner: str | None
    critical: bool
    supplier: str
    fallback: str | None
    rating: str
    measures: list[Measure]
    actions: list[str]
    swap: dict[str, Any]
    baseline: dict[str, Any] | None
    notes: str | None
    evidence_coverage: float | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class Concentration:
    supplier: str
    processes: list[str]
    share: float
    over_limit: bool


@dataclass
class Result:
    organisation: str
    assessed_by: str | None
    assessment_date: str
    settings: dict[str, Any]
    processes: list[ProcessResult]
    concentration: list[Concentration] = field(default_factory=list)
    signoff: dict[str, Any] | None = None
    method: str = "OPCP Exit-Readiness method v0.1"
    sources: list[dict[str, str]] = field(default_factory=list)  # every source cited in this result
    portfolio_refs: list[dict[str, str]] = field(default_factory=list)  # references for the concentration view

    @property
    def critical(self) -> list[ProcessResult]:
        return [p for p in self.processes if p.critical]

    def counts(self, critical_only: bool = True) -> dict[str, int]:
        pool = self.critical if critical_only else self.processes
        c = Counter(p.rating for p in pool)
        return {r: c.get(r, 0) for r in (LOCKED, PARTIAL, READY)}

    def to_dict(self) -> dict[str, Any]:
        doc = asdict(self)
        doc["summary"] = {"critical_processes": len(self.critical), "ratings": self.counts(), "generator": f"opcp {__version__}"}
        return doc


# ------------------------------------------------------------------ evaluation


def _worst(ratings: list[str]) -> str:
    return max(ratings, key=ORDER.__getitem__)


def _days(n: int) -> str:
    return f"{n} day" + ("" if n == 1 else "s")


def evaluate_process(p: Mapping[str, Any], s: Mapping[str, Any], today: dt.date) -> ProcessResult:
    m: list[Measure] = []

    logic = p["logic_ownership"]
    m.append({
        "owned": Measure("logic", "Logic ownership", "Rules and steps live in the business's own specification.", READY),
        "shared": Measure("logic", "Logic ownership", "Some rules and thresholds live in the supplier's configuration.", PARTIAL,
                          "Move the remaining rules and thresholds into the business's own process specification."),
        "vendor_held": Measure("logic", "Logic ownership", "Rules and steps live in the supplier's configuration.", LOCKED,
                               "Document the rules held in the supplier's configuration and move them into an owned process specification."),
    }[logic])

    ctx = p["context_residency"]
    m.append({
        "exportable": Measure("context", "Context residency", "Learned context can be exported in a usable form.", READY),
        "partial": Measure("context", "Context residency", "Some learned context, such as tuned scores or reviewer corrections, cannot be exported.", PARTIAL,
                           "Secure a right to export decisions, corrections and evaluation data in an open format."),
        "trapped": Measure("context", "Context residency", "Learned context cannot leave the supplier in a usable form.", LOCKED,
                           "Start writing decisions and corrections to the business's own event log now, and negotiate export rights."),
    }[ctx])

    auth = p["authority"]
    m.append({
        "ours": Measure("authority", "Authority", "Actions are governed by the business's own permission model.", READY),
        "vendor": Measure("authority", "Authority", "Actions are governed by the supplier's permission model.", PARTIAL,
                          "Route actions through the business's own authority gate, with a Reversibility Class for each action."),
        "none": Measure("authority", "Authority", "No permission model governs automated actions.", LOCKED,
                        "Define who may approve each class of action before the next release."),
    }[auth])

    deps = list(p.get("lock_in_dependencies") or [])
    limit = s["lock_in_debt_partial_max"]
    if not deps:
        m.append(Measure("debt", "Lock-in debt", "No supplier-only dependencies recorded.", READY))
    else:
        rating = PARTIAL if len(deps) <= limit else LOCKED
        m.append(Measure("debt", "Lock-in debt", f"{len(deps)} supplier-only dependenc{'y' if len(deps) == 1 else 'ies'}: {'; '.join(deps)}.", rating,
                         f"Replace supplier-only features with contract-based equivalents, starting with: {deps[0]}."))

    c = p["contract"]
    gaps = []
    if not c["termination_assistance"]:
        gaps.append("no termination assistance")
    if c.get("regulator_termination") is False:
        gaps.append("no right to terminate on a regulator's direction")
    if c["notice_days"] > s["notice_tolerance_days"]:
        gaps.append(f"{_days(c['notice_days'])} notice, above the {_days(s['notice_tolerance_days'])} tolerance")
    if not c["data_return"]:
        finding = "No data-return clause" + (f"; also {', '.join(gaps)}." if gaps else ".")
        m.append(Measure("contract", "Contract exit terms", finding, LOCKED, "Negotiate a data-return clause in an open format before renewal."))
    elif gaps:
        m.append(Measure("contract", "Contract exit terms", "Data return agreed, but " + ", ".join(gaps) + ".", PARTIAL,
                         "At renewal, close these gaps: " + "; ".join(gaps) + "."))
    else:
        m.append(Measure("contract", "Contract exit terms", "Data return, termination assistance and notice period are in place.", READY))

    t = p["time_to_swap"]
    total = t["contracting_days"] + t["onboarding_days"] + t["cutover_days"]
    tol = s["swap_tolerance_days"]
    rating = READY if total <= tol else PARTIAL if total <= 2 * tol else LOCKED
    finding = (f"{_days(total)} ({t['confidence']}): contracting {t['contracting_days']}, onboarding {t['onboarding_days']}, "
               f"cutover {t['cutover_days']}. Tolerance {_days(tol)}.")
    biggest = max(("contracting", t["contracting_days"]), ("onboarding", t["onboarding_days"]), ("cutover", t["cutover_days"]), key=lambda x: x[1])
    action = None
    if rating != READY:
        action = f"Cut the {biggest[0]} phase ({_days(biggest[1])}), the largest part of time-to-swap."
        if biggest[0] == "contracting":
            action += " Pre-qualify a second supplier so contracting is done before it is needed."
    m.append(Measure("swap", "Time-to-swap", finding, rating, action))

    fb = p.get("fallback_supplier")
    m.append(Measure("fallback", "Fallback supplier", f"{fb} identified." if fb else "None identified: single source.",
                     READY if fb else LOCKED, None if fb else "Identify and qualify a second supplier for this capability."))

    overall = _worst([x.rating for x in m])
    actions = [x.action for x in sorted(m, key=lambda x: -ORDER[x.rating]) if x.action]
    if p["critical"] and t["confidence"] == "estimated":
        actions.append("Run a shadow-mode swap drill to turn the time-to-swap estimate into a proven figure.")
    end = c.get("end_date")
    if end:
        days_left = (dt.date.fromisoformat(end) - today).days
        if days_left < 0:
            actions.insert(0, f"The contract ended on {end}: confirm the legal basis on which this supplier is still serving you.")
        elif days_left <= 365 and overall != READY:
            actions.insert(0, f"The contract ends in {_days(days_left)} ({end}): use the renewal to close the gaps listed here.")

    return ProcessResult(
        id=p["id"], name=p["name"], owner=p.get("owner"), critical=p["critical"], supplier=p["supplier"], fallback=fb,
        rating=overall, measures=m, actions=actions,
        swap={**t, "total_days": total, "tolerance_days": tol}, baseline=p.get("baseline"), notes=p.get("notes"),
    )


def evaluate(doc: Mapping[str, Any]) -> Result:
    problems = errors(schema_validator("scorecard"), doc)
    if problems:
        raise ValidationFailed("assessment", problems)
    ids = [p["id"] for p in doc["processes"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValidationFailed("assessment", [f"duplicate process id: {d}" for d in dupes])
    settings = {**DEFAULTS, **doc.get("settings", {})}
    date = doc.get("assessment_date") or dt.date.today().isoformat()
    today = dt.date.fromisoformat(date)
    processes = [evaluate_process(p, settings, today) for p in doc["processes"]]

    critical = [p for p in processes if p.critical]
    conc = []
    if critical:
        by_supplier: dict[str, list[str]] = {}
        for p in critical:
            by_supplier.setdefault(p.supplier, []).append(p.name)
        for supplier, names in sorted(by_supplier.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            share = len(names) / len(critical)
            conc.append(Concentration(supplier, names, share, share > settings["concentration_limit"]))
    return Result(doc["organisation"], doc.get("assessed_by"), date, settings, processes, conc)


def evaluate_file(path: str | Path) -> Result:
    """Rate an assessment file, or an answers file keyed by question ID."""
    doc = load_document(path)
    if isinstance(doc, Mapping) and "answers_version" in doc:
        return evaluate_answers(doc)
    return evaluate(doc)


def evaluate_answers(doc: Mapping[str, Any]) -> Result:
    """Rate an answers file: convert it through the question bank, then attach evidence and references."""
    from .questionbank import MEASURE_QUESTIONS, Bank, convert
    from .references import load_references, portfolio_refs

    bank = Bank.load()
    assessment, details, signoff = convert(bank, doc)
    if assessment["processes"]:
        result = evaluate(assessment)
    else:  # every process was triaged as not critical and left unassessed
        result = Result(assessment["organisation"], assessment.get("assessed_by"),
                        assessment.get("assessment_date") or dt.date.today().isoformat(),
                        {**DEFAULTS, **assessment.get("settings", {})}, [])
    library = load_references()
    wanted = set((doc.get("settings") or {}).get("jurisdictions") or [])
    if wanted:  # e.g. ["SG", "International"]: show only references from these jurisdictions
        library = {k: v for k, v in library.items() if v.get("jurisdiction") in wanted}
    cited: dict[str, dict[str, str]] = {}
    for proc in result.processes:
        d = details[proc.id]
        proc.evidence_coverage = d.coverage
        proc.flags = list(d.flags)
        for m in proc.measures:
            m.evidence = d.evidence.get(m.key)
            seen = set()
            for qid in MEASURE_QUESTIONS.get(m.key, ()):
                for ref in bank.questions[qid].refs:
                    key = (ref["source"], ref["at"])
                    if key in seen or ref["source"] not in library:
                        continue
                    seen.add(key)
                    src = library[ref["source"]]
                    m.refs.append({"source": ref["source"], "short": src["short"], "at": ref["at"], "url": src["url"]})
                    cited[ref["source"]] = src
    for ref in portfolio_refs():
        if ref["source"] in library:
            src = library[ref["source"]]
            result.portfolio_refs.append({"source": ref["source"], "short": src["short"], "at": ref["at"], "url": src["url"]})
            cited[ref["source"]] = src
    result.signoff = signoff
    result.method = f"OPCP Exit-Readiness method v0.1, question bank {bank.id} {bank.version}"
    result.sources = [cited[k] for k in sorted(cited, key=lambda k: cited[k]["short"])]
    return result


# ------------------------------------------------------------------ rendering

_CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#5f5f5a;--line:#e3e2dd;--ready:#1f7a4d;--ready-bg:#e6f3ec;
--partial:#8a5a00;--partial-bg:#fbf0d9;--locked:#b42318;--locked-bg:#fde8e6;--accent:#2952cc;--c1:#3f6fd8;--c2:#8a6ad8;--c3:#2e9e8f}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--card:#1f1f1d;--ink:#ecebe6;--muted:#a3a29b;--line:#34332f;
--ready:#5fc794;--ready-bg:#16301f;--partial:#e6b85c;--partial-bg:#3a2d10;--locked:#f2867c;--locked-bg:#3d1714;--accent:#8aa6ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:960px;margin:0 auto;padding:32px 16px 48px}h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:18px;margin:32px 0 12px}h3{font-size:16px;margin:0}.muted{color:var(--muted)}.small{font-size:13px}
.privacy{display:inline-block;margin-top:8px;font-size:13px;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:2px 10px}
.tiles{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:20px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.tile .n{font-size:30px;font-weight:650;line-height:1.1}.tile.locked .n{color:var(--locked)}.tile.partial .n{color:var(--partial)}.tile.ready .n{color:var(--ready)}
.headline{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:12px;padding:14px 16px;margin-top:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:14px;break-inside:avoid}
.card header{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;flex-wrap:wrap}
.badge{display:inline-block;font-size:12px;font-weight:650;border-radius:999px;padding:2px 10px;white-space:nowrap}
.badge.ready{color:var(--ready);background:var(--ready-bg)}.badge.partial{color:var(--partial);background:var(--partial-bg)}.badge.locked{color:var(--locked);background:var(--locked-bg)}
.measures{margin-top:12px}.mrow{display:grid;grid-template-columns:28% 1fr auto;gap:4px 12px;padding:8px 0;border-top:1px solid var(--line);align-items:start}
.mrow .m{font-weight:600}.mrow .r{text-align:right}
details{margin-top:4px}summary{cursor:pointer;color:var(--accent);font-size:14px}
.bar{display:flex;height:14px;border-radius:7px;overflow:hidden;background:var(--line);position:relative}
.bar span{display:block;height:100%}.seg1{background:var(--c1)}.seg2{background:var(--c2)}.seg3{background:var(--c3)}
.swapwrap{margin-top:14px}.tol{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--ink)}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:6px;font-size:12px;color:var(--muted)}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}
ol.actions{margin:12px 0 0;padding-left:20px}ol.actions li{margin:4px 0}
.ev{display:inline-block;font-size:11px;border:1px solid var(--line);border-radius:999px;padding:1px 8px;margin-top:4px;color:var(--muted)}
.ev.tested{color:var(--ready);border-color:var(--ready)}.ev.documented{color:var(--ink)}
.refs{font-size:12px;color:var(--muted);margin-top:4px}.refs a{color:var(--muted)}
.flags{margin-top:12px;border-left:3px solid var(--partial);padding:6px 10px;background:var(--partial-bg);border-radius:6px;font-size:14px}
.status{margin-top:12px;font-size:13px;color:var(--muted)}.sources li{margin:4px 0}
.conc{display:grid;grid-template-columns:minmax(120px,30%) 1fr 56px;gap:8px 12px;align-items:center}
.cbar{height:12px;background:var(--line);border-radius:6px;position:relative}.cbar span{display:block;height:100%;border-radius:6px;background:var(--accent)}
.cbar span.over{background:var(--locked)}.cbar .limit{position:absolute;top:-4px;bottom:-4px;width:2px;background:var(--ink)}
footer{margin-top:32px;font-size:13px;color:var(--muted)}
@media (max-width:600px){.tile{padding:10px}.tile .n{font-size:24px}.mrow{grid-template-columns:1fr auto;grid-template-areas:'m r' 'f f'}
.mrow .m{grid-area:m}.mrow .r{grid-area:r}.mrow .f{grid-area:f}.conc{grid-template-columns:1fr 48px}.conc>div:nth-child(3n+1){grid-column:1/-1}}
@media print{body{background:#fff}main{padding:0}.card,.tile,.headline{border-color:#ccc}}
"""


def _e(text: Any) -> str:
    return html.escape(str(text), quote=True)


def _refs_html(refs: list[dict[str, str]]) -> str:
    """Group locators by source: 'DORA Art. 28(8), 30(2)(d) · IOSCO 2021 Principle 7'."""
    grouped: dict[str, dict[str, Any]] = {}
    for r in refs:
        g = grouped.setdefault(r["source"], {"short": r["short"], "url": r["url"], "at": []})
        for part in r["at"].split(", "):
            if part not in g["at"]:
                g["at"].append(part)
    return " · ".join(f'<a href="{_e(g["url"])}">{_e(g["short"])}</a> {_e(", ".join(g["at"]))}' for g in grouped.values())


def _badge(rating: str) -> str:
    return f'<span class="badge {rating}">{LABEL[rating]}</span>'


def _swap_bar(p: ProcessResult) -> str:
    s = p.swap
    scale = max(s["total_days"], 2 * s["tolerance_days"], 1)
    segs = [("seg1", "Contracting", s["contracting_days"]), ("seg2", "Onboarding", s["onboarding_days"]), ("seg3", "Cutover", s["cutover_days"])]
    spans = "".join(f'<span class="{c}" style="width:{100 * d / scale:.2f}%" title="{n}: {d} days"></span>' for c, n, d in segs if d)
    tol = 100 * s["tolerance_days"] / scale
    legend = "".join(f'<span><i class="{c}"></i>{n} {d}d</span>' for c, n, d in segs)
    return (f'<div class="swapwrap"><div class="small muted">Time-to-swap against tolerance '
            f'({_e(s["confidence"])})</div><div class="bar" role="img" aria-label="Time-to-swap {s["total_days"]} days against a tolerance of {s["tolerance_days"]} days">'
            f'{spans}<div class="tol" style="left:{tol:.2f}%" title="Tolerance {s["tolerance_days"]} days"></div></div>'
            f'<div class="legend">{legend}<span>| tolerance {s["tolerance_days"]}d</span></div></div>')


def render_html(result: Result) -> str:
    counts = result.counts()
    crit = result.critical
    worst = max(crit, key=lambda p: (ORDER[p.rating], p.swap["total_days"]), default=None)
    headline = ""
    if worst is not None:
        headline = (f'<div class="headline"><strong>Weakest link:</strong> {_e(worst.name)} ({_e(worst.supplier)}) is '
                    f'<strong>{LABEL[worst.rating].lower()}</strong>, with an estimated {worst.swap["total_days"]}-day time-to-swap.</div>')
    tiles = "".join(f'<div class="tile {r}"><div class="n">{counts[r]}</div><div class="small muted">{LABEL[r]}</div></div>' for r in (LOCKED, PARTIAL, READY))

    limit = result.settings["concentration_limit"]
    rows = []
    for c in result.concentration:
        names = ", ".join(c.processes)
        rows.append(f'<div class="small"><strong>{_e(c.supplier)}</strong><br><span class="muted">{_e(names)}</span></div>'
                    f'<div class="cbar"><span class="{"over" if c.over_limit else ""}" style="width:{100 * c.share:.1f}%"></span>'
                    f'<div class="limit" style="left:{100 * limit:.1f}%" title="Limit {limit:.0%}"></div></div>'
                    f'<div class="small"><strong>{c.share:.0%}</strong>{" ⚠" if c.over_limit else ""}</div>')
    over = [c for c in result.concentration if c.over_limit]
    conc_note = (f'<p class="small">{"; ".join(f"{_e(c.supplier)} is primary for {c.share:.0%} of critical processes" for c in over)}, '
                 f'above the {limit:.0%} limit.</p>' if over else f'<p class="small muted">No supplier exceeds the {limit:.0%} limit.</p>')

    cards = []
    for p in sorted(result.processes, key=lambda p: (not p.critical, -ORDER[p.rating], p.name)):
        measures = "".join(
            f'<div class="mrow"><div class="m">{_e(x.name)}'
            + (f'<br><span class="ev {x.evidence}">{_e(EVIDENCE_LABEL[x.evidence])}</span>' if x.evidence else "")
            + f'</div><div class="f">{_e(x.finding)}'
            + (f'<div class="refs">Relates to: {_refs_html(x.refs)}</div>' if x.refs else "")
            + f'</div><div class="r">{_badge(x.rating)}</div></div>'
            for x in p.measures)
        coverage = ""
        if p.evidence_coverage is not None:
            coverage = (f'<p class="small muted">Evidence: {p.evidence_coverage:.0%} of answers are backed by a record or a test; '
                        f'each measure shows its weakest supporting evidence.</p>')
        flags = ""
        if p.flags:
            flags = '<div class="flags"><strong>Check these answers</strong><ul style="margin:4px 0 0;padding-left:18px">' + "".join(f"<li>{_e(f)}</li>" for f in p.flags) + "</ul></div>"
        top, rest = p.actions[:3], p.actions[3:]
        actions = ""
        if top:
            actions = '<h3 style="margin-top:14px;font-size:14px">Top actions</h3><ol class="actions">' + "".join(f"<li>{_e(a)}</li>" for a in top) + "</ol>"
        if rest:
            more = "".join(f"<li>{_e(a)}</li>" for a in rest)
            label = f'{len(rest)} more action{"s" if len(rest) > 1 else ""}'
            actions += f'<details><summary>{label}</summary><ol class="actions" start="4">{more}</ol></details>'
        base = ""
        if p.baseline:
            b = p.baseline
            parts = []
            if "cycle_time_hours" in b:
                parts.append(f"cycle time {b['cycle_time_hours']:g} h")
            if "straight_through_rate" in b:
                parts.append(f"straight-through {b['straight_through_rate']:.0%}")
            if "exception_rate" in b:
                parts.append(f"exceptions {b['exception_rate']:.0%}")
            if "cost_per_case" in b:
                parts.append(f"cost per case {b['cost_per_case']:g} {b.get('currency', '')}".strip())
            base = f'<p class="small muted">Operational baseline: {_e(", ".join(parts))}</p>'
        notes = f'<p class="small muted">{_e(p.notes)}</p>' if p.notes else ""
        who = " · ".join(x for x in [f"Owner: {p.owner}" if p.owner else "", "Critical" if p.critical else "Not critical"] if x)
        cards.append(
            f'<section class="card" id="{_e(p.id)}"><header><div><h3>{_e(p.name)}</h3>'
            f'<div class="small muted">{_e(who)} · Supplier: {_e(p.supplier)} · Fallback: {_e(p.fallback or "none")}</div></div>'
            f'<div>{_badge(p.rating)}</div></header>{_swap_bar(p)}<div class="measures">{measures}</div>'
            + coverage + flags + actions
            + base + notes + "</section>"
        )

    meta = " · ".join(x for x in [_e(result.assessment_date), f"Assessed by {_e(result.assessed_by)}" if result.assessed_by else ""] if x)
    s = result.settings
    so = result.signoff or {}
    def person(d):
        return ", ".join(x for x in (d.get("name"), d.get("role")) if x) + (f" on {d['date']}" if d.get("date") else "")
    review = (f"Reviewed by {_e(person(so['reviewed_by']))}." if so.get("reviewed_by")
              else "<strong>Not independently reviewed.</strong>")
    status = (f'<p class="status">Self-assessment against the {_e(result.method)}. Not a certification. '
              + (f"Prepared by {_e(person(so['prepared_by']))}. " if so.get("prepared_by") else "") + review + "</p>")
    conc_refs = (f'<div class="refs">Relates to: {_refs_html(result.portfolio_refs)}</div>' if result.portfolio_refs else "")
    not_assessed = so.get("not_assessed") or []
    skipped = (f'<p class="small muted">Not assessed (triaged as not critical): {_e(", ".join(not_assessed))}.</p>' if not_assessed else "")
    sources = ""
    if result.sources:
        items = "".join(f'<li><a href="{_e(x["url"])}">{_e(x["title"])}</a>, {_e(x["publisher"])}, {_e(x["date"])}. '
                        f'{_e(x.get("status", ""))}. <span class="muted">Checked via: {_e(x.get("verified_via", ""))}</span></li>' for x in result.sources)
        sources = (f'<p><strong>Sources cited.</strong> Locators were checked on 24 October 2026; confirm them against the official text before relying on them.</p>'
                   f'<ul class="sources small">{items}</ul>')
    else:
        sources = ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Exit-Readiness Scorecard · {_e(result.organisation)}</title><style>{_CSS}</style></head><body><main>
<div class="small muted">Exit-Readiness Scorecard</div><h1>{_e(result.organisation)}</h1><div class="muted">{meta}</div>
<div class="privacy">Generated locally by OPCP {__version__}. No data left this machine.</div>{status}
<h2>Critical processes</h2><div class="tiles">{tiles}</div>{headline}{skipped}
<h2>Supplier concentration</h2><p class="small muted">Share of critical processes for which each supplier is primary. The vertical line is the limit.</p>
<div class="conc">{''.join(rows) or '<p class="muted">No critical processes assessed.</p>'}</div>{conc_note}{conc_refs}
<h2>Processes</h2>{''.join(cards)}
<footer><p><strong>Method.</strong> Each process is rated by its weakest measure, because an exit fails at its weakest point.
Tolerances used: time-to-swap {s['swap_tolerance_days']} days, notice period {s['notice_tolerance_days']} days,
lock-in debt up to {s['lock_in_debt_partial_max']} dependencies for Partial, concentration limit {s['concentration_limit']:.0%}.
Time-to-swap is estimated unless proven by a swap drill.</p>
<p>Open Process Control Plane specification v0.1, section 12. References show which published obligations a measure relates to; they do not mean the firm complies with them. This report supports, and does not replace, regulatory obligations; it is not legal or regulatory advice.</p>{sources}</footer>
</main></body></html>"""


def render_json(result: Result) -> str:
    return json.dumps(result.to_dict(), indent=2)


def render_text(result: Result) -> str:
    counts = result.counts()
    lines = [f"Exit-Readiness Scorecard: {result.organisation} ({result.assessment_date})",
             f"Critical processes: {counts[LOCKED]} locked, {counts[PARTIAL]} partial, {counts[READY]} ready", ""]
    for p in sorted(result.processes, key=lambda p: (not p.critical, -ORDER[p.rating], p.name)):
        lines.append(f"[{LABEL[p.rating]:>7}] {p.name} ({p.supplier}) - time-to-swap {p.swap['total_days']} days, {p.swap['confidence']}")
        for a in p.actions[:3]:
            lines.append(f"          - {a}")
    over = [c for c in result.concentration if c.over_limit]
    for c in over:
        lines.append(f"\nConcentration: {c.supplier} is primary for {c.share:.0%} of critical processes "
                     f"(limit {result.settings['concentration_limit']:.0%}).")
    return "\n".join(lines)


TEMPLATE = """\
# Exit-Readiness Scorecard assessment
# Fill in one entry under `processes` for each process you want to assess, then run:
#   opcp scorecard run this-file.yaml -o report.html
# Everything runs on this machine. Nothing is sent anywhere.

scorecard_version: "0.1"
organisation: Your organisation
assessed_by: Your name
assessment_date: "{today}"

settings:
  swap_tolerance_days: 90        # The longest time-to-swap you can accept for a critical process.
  notice_tolerance_days: 90      # The longest supplier notice period you can accept.
  concentration_limit: 0.5       # Largest share of critical processes one supplier may serve as primary.
  lock_in_debt_partial_max: 3    # More supplier-only dependencies than this rates as Locked.

processes:
  - id: customer-onboarding-idv          # Short identifier: lowercase letters, digits and hyphens.
    name: Customer onboarding, identity verification
    owner: Head of Retail Operations
    critical: true                       # Would disruption harm customers or breach an obligation?
    capability: verify-identity          # Optional: the OPCP capability this process step uses.
    archetype: check                     # Optional: check, extract, generate, transact, retrieve, notify, human_task
    supplier: Current vendor name
    fallback_supplier: null              # A qualified second supplier, or null if there is none.

    # Where do the rules and steps live?  owned | shared | vendor_held
    logic_ownership: vendor_held
    # Can learned context (decisions, corrections, tuned scores) leave in a usable form?  exportable | partial | trapped
    context_residency: partial
    # Whose permission model governs automated actions?  ours | vendor | none
    authority: vendor
    # Features only this supplier provides, which a replacement would have to rebuild.
    lock_in_dependencies:
      - Proprietary risk signal
      - Console-only escalation workflow

    contract:
      data_return: true                  # Does the contract require return of your data in a usable format?
      termination_assistance: false      # Must the supplier help you migrate away?
      notice_days: 180
      end_date: "2027-06-30"             # Optional.

    # Your best estimate of days to replace this supplier, in three parts.
    time_to_swap:
      contracting_days: 70               # Due diligence and agreement with a new supplier.
      onboarding_days: 30                # Security review and any regulator notification.
      cutover_days: 20                   # Technical switch, data migration and testing.
      confidence: estimated              # estimated | proven (proven only after a swap drill)

    # Optional: the operational baseline, so improvements can be measured.
    # baseline:
    #   cycle_time_hours: 26
    #   straight_through_rate: 0.72
    #   exception_rate: 0.18
    #   cost_per_case: 4.10
    #   currency: SGD

    notes: Anything a reviewer should know.
"""


def template(today: dt.date | None = None) -> str:
    return TEMPLATE.format(today=(today or dt.date.today()).isoformat())
