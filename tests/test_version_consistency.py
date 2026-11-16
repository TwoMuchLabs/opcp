"""Version consistency checks.

These guard relationships between version numbers that hold under every versioning
option in docs/adr/0001-versioning-model.md. They do not decide that ADR: in particular
they do not check the header of spec/SPEC.md, which is the open question.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

import opcp
from opcp import envelope

ROOT = Path(__file__).resolve().parent.parent

# Each schema and the property that carries its format version.
SCHEMA_VERSION_FIELD = {
    "capability": ("opcp_version",),
    "route": ("opcp_version",),
    "swap-drill": ("opcp_version",),
    "scorecard": ("scorecard_version",),
    "answers": ("answers_version",),
    "envelope": ("$defs", "request", "envelope_version"),
}


def _package_version() -> str:
    # tomllib is not available on Python 3.10, which CI still supports.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    project = text.split("[project]", 1)[1].split("\n[", 1)[0]
    m = re.search(r'^version\s*=\s*"([^"]+)"', project, re.M)
    assert m, "no version in [project]"
    return m.group(1)


def _schema(name: str) -> dict:
    return json.loads((ROOT / "schema" / f"{name}.schema.json").read_text(encoding="utf-8"))


def _format_version(name: str) -> str:
    """The `const` a schema requires for its version field."""
    doc = _schema(name)
    path = SCHEMA_VERSION_FIELD[name]
    if path[0] == "$defs":
        node = doc["$defs"][path[1]]["properties"][path[2]]
    else:
        node = doc["properties"][path[0]]
    return node["const"]


def test_package_version_is_the_same_in_pyproject_and_module():
    # Guarantee: the version a user sees from `opcp --version` is the version on PyPI.
    assert opcp.__version__ == _package_version()


def test_package_version_has_changelog_entry():
    # Guarantee: every released package version is described in the changelog.
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## {re.escape(_package_version())}\b", changelog, re.M), (
        f"CHANGELOG.md has no '## {_package_version()}' heading")


def test_package_version_has_release_notes():
    # Guarantee: the release workflow will find the notes it requires.
    assert (ROOT / "docs" / "releases" / f"v{_package_version()}.md").is_file()


def test_readme_status_names_package_major_minor():
    # Guarantee: the README does not advertise a different release than the package.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"\*\*Status:\*\*\s*draft\s+(\d+\.\d+)", readme)
    assert m, "README status line not found"
    major_minor = ".".join(_package_version().split(".")[:2])
    assert m.group(1) == major_minor


@pytest.mark.parametrize("path", sorted((ROOT / "schema").glob("*.schema.json")), ids=lambda p: p.name)
def test_schema_id_version_matches_its_own_version_const(path):
    # Guarantee: a schema's identifier and the documents it accepts agree on the format version.
    name = path.name.removesuffix(".schema.json")
    doc = json.loads(path.read_text(encoding="utf-8"))
    m = re.fullmatch(r"urn:opcp:schema:(\d+\.\d+):" + re.escape(name), doc["$id"])
    assert m, f"unexpected $id {doc['$id']!r}"
    if name in SCHEMA_VERSION_FIELD:
        assert m.group(1) == _format_version(name)


def test_runtime_envelope_version_matches_schema():
    # Guarantee: envelopes the reference runtime emits declare the version the schema accepts.
    assert envelope.ENVELOPE_VERSION == _format_version("envelope")
    response = _schema("envelope")["$defs"]["response"]["properties"]["envelope_version"]["const"]
    assert response == envelope.ENVELOPE_VERSION


@pytest.mark.parametrize("path", sorted((ROOT / "catalogue").glob("*.yaml")), ids=lambda p: p.name)
def test_catalogue_contracts_carry_capability_format_version(path):
    # Guarantee: the published catalogue is valid for the capability schema in this release.
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert doc["opcp_version"] == _format_version("capability")


def test_swap_drill_example_and_evaluator_use_schema_format_version():
    # Guarantee: the evaluator accepts exactly the evidence format the schema defines,
    # and the shipped example uses it.
    version = _format_version("swap-drill")
    example = json.loads((ROOT / "examples" / "sme-credit-swap-drill.json").read_text(encoding="utf-8"))
    assert example["opcp_version"] == version
    for module in ("swap.py", "swap_drill.py"):
        literals = set(re.findall(r'"opcp_version"\)?\s*(?:!=|==|:)\s*"(\d+\.\d+)"',
                                  (ROOT / "opcp" / module).read_text(encoding="utf-8")))
        assert literals == {version}, f"{module} uses {literals}, schema requires {version}"


def test_swap_drill_spec_title_names_format_version():
    # Guarantee: the normative swap-drill text and its schema describe the same format version.
    title = (ROOT / "spec" / "SWAP-DRILL.md").read_text(encoding="utf-8").splitlines()[0]
    assert title.endswith(f"OPCP v{_format_version('swap-drill')}"), title
