"""Version markers must stay consistent with each other (docs/VERSIONING.md).

Tests marked xfail(strict=True) record inconsistencies that exist on main and need a maintainer
decision (docs/adr/0001-versioning-model.md). When one is fixed the test passes, pytest reports
XPASS as a failure, and the marker must be removed in the same change.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

import opcp
from opcp.envelope import ENVELOPE_VERSION

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS = {p.stem.removesuffix(".schema"): json.loads(p.read_text(encoding="utf-8"))
           for p in sorted((ROOT / "schema").glob("*.schema.json"))}
ID_PATTERN = re.compile(r"^urn:opcp:schema:(?P<version>\d+\.\d+):(?P<name>[a-z-]+)$")


def package_version() -> str:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def const_versions(schema: dict) -> dict[str, str]:
    """Every `<something>_version: {const: ...}` property, at any depth."""
    found: dict[str, str] = {}

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.get("properties", {}).items():
                if key.endswith("_version") and isinstance(value, dict) and "const" in value:
                    found[key] = value["const"]
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return found


def major_minor(version: str) -> str:
    return ".".join(version.split(".")[:2])


def spec_header_version() -> str:
    match = re.search(r"^\*\*Version:\*\* (\d+\.\d+(?:\.\d+)?)", (ROOT / "spec" / "SPEC.md").read_text(encoding="utf-8"), re.M)
    assert match, "spec/SPEC.md must state its version as '**Version:** X.Y.Z'"
    return match[1]


def swap_drill_spec_version() -> str:
    match = re.search(r"^# .*OPCP v(\d+\.\d+)", (ROOT / "spec" / "SWAP-DRILL.md").read_text(encoding="utf-8"), re.M)
    assert match, "spec/SWAP-DRILL.md must state its version in its title"
    return match[1]


# ---------------------------------------------------------------- relationships that hold today


def test_package_version_is_declared_once():
    """The package version in pyproject.toml is the one the code reports (`opcp --version`, report footers)."""
    assert opcp.__version__ == package_version()


def test_package_version_has_changelog_and_release_notes():
    """Every package version has a CHANGELOG entry and release notes; the release workflow requires the notes."""
    version = package_version()
    assert re.search(rf"^## {re.escape(version)}\b", (ROOT / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    assert (ROOT / "docs" / "releases" / f"v{version}.md").is_file()


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_schema_id_is_well_formed_and_matches_its_version_field(name):
    """A schema's $id names the schema and carries the same version as the document format it validates."""
    schema = SCHEMAS[name]
    match = ID_PATTERN.match(schema.get("$id", ""))
    assert match, f"{name}: $id {schema.get('$id')!r} is not urn:opcp:schema:<major.minor>:<name>"
    assert match["name"] == name
    for field, value in const_versions(schema).items():
        assert value == match["version"], f"{name}: {field} is {value!r} but $id says {match['version']!r}"


def test_bundled_contracts_use_the_format_version_the_schema_accepts():
    """Every catalogue contract declares the opcp_version its schema accepts."""
    expected = const_versions(SCHEMAS["capability"])["opcp_version"]
    for path in sorted((ROOT / "catalogue").glob("*.yaml")):
        assert yaml.safe_load(path.read_text(encoding="utf-8"))["opcp_version"] == expected, path.name


def test_bundled_swap_drill_examples_use_the_format_version_the_schema_accepts():
    expected = const_versions(SCHEMAS["swap-drill"])["opcp_version"]
    for path in sorted((ROOT / "examples").glob("*swap-drill*.json")):
        assert json.loads(path.read_text(encoding="utf-8"))["opcp_version"] == expected, path.name


def test_runtime_envelope_version_matches_schema():
    """The reference runtime emits the envelope version the schema requires, for requests and responses."""
    assert set(const_versions(SCHEMAS["envelope"]).values()) == {ENVELOPE_VERSION}


def test_every_schema_is_recorded_in_the_versioning_page():
    """A new schema or version field cannot appear without docs/VERSIONING.md saying what it versions."""
    page = (ROOT / "docs" / "VERSIONING.md").read_text(encoding="utf-8")
    for name, schema in SCHEMAS.items():
        versioned = const_versions(schema)
        if versioned:
            assert f"schema/{name}.schema.json" in page, f"docs/VERSIONING.md does not mention schema/{name}.schema.json"
        for field in versioned:
            assert f"`{field}`" in page, f"docs/VERSIONING.md does not explain `{field}`"


# ---------------------------------------------------------------- known inconsistencies (ADR 0001)


@pytest.mark.xfail(strict=True, reason="spec/SPEC.md says 0.2.0 while spec/SWAP-DRILL.md says v0.3; see docs/VERSIONING.md finding 3")
def test_companion_specification_matches_core_specification_version():
    assert major_minor(swap_drill_spec_version()) == major_minor(spec_header_version())


@pytest.mark.xfail(strict=True, reason="opcp.SPEC_VERSION is unused and says 0.1; see docs/VERSIONING.md finding 5")
def test_runtime_states_the_specification_version_it_implements():
    assert opcp.SPEC_VERSION == major_minor(spec_header_version())
