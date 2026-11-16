"""Loading YAML or JSON documents and validating them against the bundled schemas."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker

from ._paths import data_dir


class _StringDateLoader(yaml.SafeLoader):
    """SafeLoader that keeps dates and timestamps as strings, so they validate as JSON strings."""


_StringDateLoader.yaml_implicit_resolvers = {
    key: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


# YAML aliases can make a small file expand into an enormous document ("billion laughs"); the
# expansion happens when the document is validated or serialised, not when it is parsed. No OPCP
# document comes anywhere near this many values.
MAX_YAML_NODES = 1_000_000


def _expanded_size(root: yaml.Node) -> int:
    """How many nodes the document has once every alias is expanded (shared nodes counted each time)."""
    memo: dict[int, int] = {}

    def size(node: yaml.Node) -> int:
        key = id(node)
        if key in memo:
            return memo[key]
        memo[key] = 1  # a self-referencing alias counts once rather than looping
        if isinstance(node, yaml.MappingNode):
            total = 1 + sum(size(k) + size(v) for k, v in node.value)
        elif isinstance(node, yaml.SequenceNode):
            total = 1 + sum(size(item) for item in node.value)
        else:
            total = 1
        memo[key] = total
        return total

    return size(root)


def load_document(path: str | Path) -> Any:
    """Load a YAML or JSON file."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    loader = _StringDateLoader(text)  # a safe loader subclass
    try:
        node = loader.get_single_node()
        if node is None:
            return None
        if _expanded_size(node) > MAX_YAML_NODES:
            raise ValidationFailed(str(path), [f"expands to more than {MAX_YAML_NODES:,} values through YAML aliases"])
        return loader.construct_document(node)
    finally:
        loader.dispose()


# JSON Schema 2020-12 treats "format" as an annotation unless a validator chooses to assert it, and
# python-jsonschema asserts some formats only when optional packages happen to be installed. Without
# a fixed list, "date" was checked everywhere but "date-time" and "uri" only on machines that had
# those packages, so the same document could pass on one machine and fail on another. These formats
# are always asserted (their checkers ship with jsonschema or with the two validators OPCP depends
# on); any other format is an annotation only, everywhere. The checkers are taken from the draft
# 2020-12 set: jsonschema's global FormatChecker registry maps "time" to the draft-3 checker
# (HH:MM:SS, no offset). A listed checker that is unavailable raises KeyError at import, so a missing
# dependency cannot silently weaken validation.
ENFORCED_FORMATS = ("date", "date-time", "time", "uri", "uri-reference", "email", "ipv4", "ipv6", "uuid", "regex")


def _format_checker() -> FormatChecker:
    available = Draft202012Validator.FORMAT_CHECKER.checkers
    missing = [name for name in ENFORCED_FORMATS if name not in available]
    if missing:
        raise ImportError(f"jsonschema cannot check the {', '.join(missing)} format(s); install OPCP's dependencies "
                          "(rfc3339-validator, rfc3986-validator), for example with `pip install opcp`")
    checker = FormatChecker(formats=())
    for name in ENFORCED_FORMATS:
        checker.checkers[name] = available[name]
    return checker


FORMAT_CHECKER = _format_checker()


@lru_cache(maxsize=None)
def schema_validator(name: str) -> Draft202012Validator:
    """Validator for a bundled schema, e.g. ``capability``, ``route``, ``scorecard``."""
    schema = json.loads((data_dir("schema") / f"{name}.schema.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


def validator_for(schema: dict) -> Draft202012Validator:
    """Validator for an ad hoc schema, such as a contract's input or output."""
    return Draft202012Validator(schema, format_checker=FORMAT_CHECKER)


def errors(validator: Draft202012Validator, document: Any, *, redact: bool = False) -> list[str]:
    """Human-readable validation errors, with the path to each offending field.

    With ``redact=True`` the message names only the field and the rule it broke, never the value,
    so it is safe to write to a log that must not hold input values.
    """
    found = []
    for err in sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(document)"
        found.append(f"{where}: fails '{err.validator}' rule" if redact else f"{where}: {err.message}")
    return found


class ValidationFailed(ValueError):
    """A document did not validate. ``problems`` lists each error."""

    def __init__(self, what: str, problems: list[str]):
        self.problems = problems
        super().__init__(f"{what} is not valid:\n  - " + "\n  - ".join(problems))
