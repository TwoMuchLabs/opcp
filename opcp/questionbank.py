"""The standard question bank and answers files (spec section 12.6).

An answers file records, for each process, the answer to each question by its stable ID, with the
evidence behind it. This module checks answers against the bank, turns them into the fields the
scorecard rates, and works out the evidence level behind each measure.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from ._io import ValidationFailed, errors, load_document, schema_validator
from ._paths import data_dir

EVIDENCE_ORDER = ("declared", "documented", "tested")

# Which questions feed which scorecard measure. A measure's evidence is its weakest supporting answer.
MEASURE_QUESTIONS: dict[str, tuple[str, ...]] = {
    "logic": ("ERS-LOG-01",),
    "context": ("ERS-DAT-01",),
    "authority": ("ERS-AUT-01",),
    "debt": ("ERS-DEP-01",),
    "contract": ("ERS-CON-01", "ERS-CON-02", "ERS-CON-03", "ERS-CON-04"),
    "swap": ("ERS-EXT-01", "ERS-EXT-02", "ERS-EXT-03", "ERS-EXT-04"),
    "fallback": ("ERS-DEP-02",),
}
TRIAGE = ("ERS-TRI-01", "ERS-TRI-02", "ERS-TRI-03")


@dataclass(frozen=True)
class Question:
    id: str
    section: str
    role: str
    ask: str
    type: str
    feeds: Any
    options: tuple[Mapping[str, str], ...] = ()
    help: str | None = None
    required: bool = True
    unit: str | None = None
    evidence: Mapping[str, str] = field(default_factory=dict)
    refs: tuple[Mapping[str, str], ...] = ()

    @property
    def values(self) -> tuple[str, ...]:
        return tuple(o["value"] for o in self.options)

    def label_for(self, value: Any) -> str:
        for o in self.options:
            if o["value"] == value:
                return o["label"]
        return str(value)


@dataclass
class Bank:
    id: str
    version: str
    title: str
    questions: dict[str, Question]
    sections: list[Mapping[str, str]]
    roles: Mapping[str, str]
    evidence_levels: Mapping[str, Mapping[str, str]]
    consistency: list[Mapping[str, Any]]
    raw: Mapping[str, Any] = field(repr=False, default_factory=dict)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Bank":
        doc = load_document(path or data_dir("questions") / "exit-readiness.yaml")
        problems = errors(schema_validator("question-bank"), doc)
        if problems:
            raise ValidationFailed("question bank", problems)
        questions = {}
        for q in doc["questions"]:
            if q["id"] in questions:
                raise ValidationFailed("question bank", [f"duplicate question id {q['id']}"])
            questions[q["id"]] = Question(
                id=q["id"], section=q["section"], role=q["role"], ask=q["ask"], type=q["type"], feeds=q["feeds"],
                options=tuple(q.get("options", ())), help=q.get("help"), required=q.get("required", True),
                unit=q.get("unit"), evidence=q.get("evidence", {}), refs=tuple(q.get("refs", ())),
            )
        return cls(doc["bank"], doc["bank_version"], doc["title"], questions, doc["sections"], doc["roles"],
                   doc["evidence_levels"], doc.get("consistency", []), doc)


# ------------------------------------------------------------------ answers


@dataclass
class ProcessAnswers:
    """One process's answers, converted for the scorecard."""

    fields: dict[str, Any]
    evidence: dict[str, str]  # measure key -> weakest evidence level
    coverage: float  # share of answered rated questions backed by a record or a test
    flags: list[str]
    references: dict[str, list[str]]  # question id -> evidence references given


def _set(target: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    for p in parts[:-1]:
        target = target.setdefault(p, {})
    target[parts[-1]] = value


def _value(answers: Mapping[str, Any], qid: str) -> Any:
    a = answers.get(qid)
    return None if a is None else a.get("value")


def _check_rule(rule: Mapping[str, Any], answers: Mapping[str, Any]) -> bool:
    for qid, cond in rule["when"].items():
        v = _value(answers, qid)
        present = v not in (None, "", [])
        if cond == "present":
            ok = present
        elif cond == "absent":
            ok = not present
        elif isinstance(cond, list):
            ok = v in cond
        elif isinstance(cond, Mapping) and "above" in cond:
            ok = isinstance(v, (int, float)) and v > cond["above"]
        else:
            ok = v == cond
        if not ok:
            return False
    return True


def convert_process(bank: Bank, proc: Mapping[str, Any], where: str) -> tuple[ProcessAnswers, list[str]]:
    """Return converted answers and any problems found, each prefixed with ``where``."""
    answers: Mapping[str, Any] = proc.get("answers", {})
    problems: list[str] = []
    for qid in answers:
        if qid not in bank.questions:
            problems.append(f"{where}: unknown question {qid}")
    fields: dict[str, Any] = {k: proc[k] for k in ("id", "name", "owner", "supplier", "capability", "archetype", "notes", "mappings") if k in proc}
    refs: dict[str, list[str]] = {}

    for q in bank.questions.values():
        a = answers.get(q.id)
        v = None if a is None else a.get("value")
        missing = a is None or v is None or v == ""
        if missing:
            if q.required and q.type not in ("list", "text"):
                problems.append(f"{where}: {q.id} is not answered ({q.ask})")
            if q.type == "list" and isinstance(q.feeds, Mapping):
                _set(fields, q.feeds["field"], [])
            if q.type == "text" and isinstance(q.feeds, Mapping):
                _set(fields, q.feeds["field"], None)
            continue
        if q.type == "choice" and v not in q.values:
            problems.append(f"{where}: {q.id} must be one of {', '.join(q.values)}, not {v!r}")
            continue
        numeric = isinstance(v, (int, float)) and not isinstance(v, bool)
        if q.type == "number" and (not numeric or v < 0):
            problems.append(f"{where}: {q.id} must be a number of {q.unit or 'units'} of zero or more")
            continue
        if q.type == "number" and q.unit == "days" and not float(v).is_integer():
            problems.append(f"{where}: {q.id} must be a whole number of days")
            continue
        if q.type == "percent" and (not numeric or not 0 <= v <= 100):
            problems.append(f"{where}: {q.id} must be a percentage between 0 and 100")
            continue
        if q.type == "date":
            try:
                dt.date.fromisoformat(str(v))
                if not isinstance(v, str) or len(v) != 10:
                    raise ValueError
            except ValueError:
                problems.append(f"{where}: {q.id} must be a date written as YYYY-MM-DD")
                continue
        if q.type == "text" and not isinstance(v, str):
            problems.append(f"{where}: {q.id} must be text")
            continue
        if q.type == "list" and not (isinstance(v, list) and all(isinstance(i, str) for i in v)):
            problems.append(f"{where}: {q.id} must be a list of short descriptions")
            continue
        level = a.get("evidence", "declared")
        if level not in EVIDENCE_ORDER:
            problems.append(f"{where}: {q.id} evidence must be declared, documented or tested")
        elif level != "declared" and not a.get("ref"):
            problems.append(f"{where}: {q.id} is marked {level}; name the record in 'ref'")
        if a.get("ref"):
            refs[q.id] = [a["ref"]]
        if not isinstance(q.feeds, Mapping):
            continue
        target = q.feeds["field"]
        if q.type == "choice" and q.values == ("yes", "no"):
            v = v == "yes"
        if q.type == "percent":
            v = v / 100
        if q.type == "number" and target.startswith("time_to_swap."):
            v = int(v)
        _set(fields, target, v)

    fields["critical"] = any(_value(answers, t) == "yes" for t in TRIAGE)
    tts = fields.setdefault("time_to_swap", {})
    tts["confidence"] = "proven" if tts.get("drill_date") else "estimated"
    if not tts.get("drill_date"):
        tts.pop("drill_date", None)
    contract = fields.setdefault("contract", {})
    if contract.get("end_date") in (None, ""):
        contract.pop("end_date", None)
    baseline = fields.get("baseline")
    if baseline is not None and not baseline:
        fields.pop("baseline")

    evidence: dict[str, str] = {}
    rated, backed = 0, 0
    for measure, qids in MEASURE_QUESTIONS.items():
        levels = []
        for qid in qids:
            a = answers.get(qid)
            if a is None or a.get("value") in (None, ""):  # an empty list is an answer: "none"
                continue
            level = a.get("evidence", "declared")
            levels.append(level if level in EVIDENCE_ORDER else "declared")
        if levels:
            evidence[measure] = min(levels, key=EVIDENCE_ORDER.index)
            rated += len(levels)
            backed += sum(1 for lv in levels if lv != "declared")
    flags = [r["says"] for r in bank.consistency if _check_rule(r, answers)]
    return ProcessAnswers(fields, evidence, (backed / rated) if rated else 0.0, flags, refs), problems


def convert(bank: Bank, doc: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, ProcessAnswers], dict[str, Any]]:
    """Turn an answers file into (assessment for the scorecard, per-process answer details, sign-off)."""
    problems = errors(schema_validator("answers"), doc)
    if problems:
        raise ValidationFailed("answers file", problems)
    if doc["bank"] != bank.id or doc["bank_version"] != bank.version:
        raise ValidationFailed("answers file", [f"answers are for {doc['bank']} {doc['bank_version']}, "
                                                f"but this tool has {bank.id} {bank.version}"])
    details: dict[str, ProcessAnswers] = {}
    processes = []
    skipped: list[str] = []
    for i, proc in enumerate(doc["processes"]):
        answers = proc.get("answers", {})
        triaged_out = all(_value(answers, t) == "no" for t in TRIAGE)
        converted, found = convert_process(bank, proc, f"processes/{i} ({proc.get('id', '?')})")
        if triaged_out and found and all("is not answered" in f for f in found):
            skipped.append(proc["name"])  # not critical and not fully assessed: listed, not rated
            continue
        problems += found
        details[proc["id"]] = converted
        processes.append(converted.fields)
    if problems:
        raise ValidationFailed("answers file", problems)
    assessment = {
        "scorecard_version": "0.1",
        "organisation": doc["organisation"],
        "processes": processes,
    }
    if "assessment_date" in doc:
        assessment["assessment_date"] = doc["assessment_date"]
    if "settings" in doc:  # display-only options such as `jurisdictions` stay out of the rating settings
        assessment["settings"] = {k: v for k, v in doc["settings"].items() if k != "jurisdictions"}
    prepared = doc.get("prepared_by", {})
    if prepared:
        assessment["assessed_by"] = ", ".join(x for x in (prepared.get("name"), prepared.get("role")) if x)
    signoff = {"prepared_by": doc.get("prepared_by"), "reviewed_by": doc.get("reviewed_by"), "not_assessed": skipped}
    return assessment, details, signoff
