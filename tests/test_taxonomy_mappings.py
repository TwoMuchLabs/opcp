"""Mappings to external taxonomies (APQC PCF, BIAN, ISO 20022): see docs/TAXONOMIES.md."""

import copy
import json
import re

import pytest

from opcp._io import ValidationFailed, load_document
from opcp._paths import data_dir
from opcp.contract import Contract
from opcp.questionbank import Bank, convert
from opcp.scorecard import evaluate_answers

ANSWERS = load_document(data_dir("examples") / "example-bank-answers.yaml")
CATALOGUE_DIR = data_dir("catalogue")


def test_every_catalogue_entry_maps_to_a_bian_service_domain_with_a_source():
    for path in sorted(CATALOGUE_DIR.glob("*.yaml")):
        doc = load_document(path)
        Contract.from_dict(doc)  # validates against the schema
        bian = doc["mappings"]["bian_service_domain"]
        assert bian["ref"] and bian["source"].startswith("https://"), path.name
        assert bian["version"] == "14.0.0", path.name
        assert bian["relation"] in ("exact", "closest", "partial"), path.name
        assert "apqc_pcf" in doc["mappings"], path.name  # present, even if not yet mapped


BIAN_FILE = re.compile(r"^https://github\.com/bian-official/public/blob/[0-9a-f]{40}/release14\.0\.0/"
                       r"semantic-apis/oas3%20/yamls/(?P<name>[A-Za-z]+)\.yaml$")


def test_bian_sources_link_the_service_domain_itself_at_a_fixed_commit():
    # A folder or a moving branch can't be checked later; the item's own file at a commit can.
    for path in sorted(CATALOGUE_DIR.glob("*.yaml")):
        bian = load_document(path)["mappings"]["bian_service_domain"]
        m = BIAN_FILE.match(bian["source"])
        assert m, (path.name, bian["source"])
        assert m["name"] == bian["ref"].replace(" ", ""), path.name


def test_mapping_is_defined_once_and_identically_in_every_schema():
    defs = {}
    for name in ("capability", "answers", "scorecard"):
        doc = json.loads((data_dir("schema") / f"{name}.schema.json").read_text(encoding="utf-8"))
        defs[name] = doc["$defs"]["mapping"]
        uses = list(_mappings_properties(doc))
        assert uses, name
        for prop in uses:  # every `mappings` property points at the one definition
            assert prop["additionalProperties"]["oneOf"] == [{"type": "null"}, {"$ref": "#/$defs/mapping"}], name
    assert defs["capability"] == defs["answers"] == defs["scorecard"]


def _mappings_properties(node):
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict) and "mappings" in node["properties"]:
            yield node["properties"]["mappings"]
        for value in node.values():
            yield from _mappings_properties(value)
    elif isinstance(node, list):
        for value in node:
            yield from _mappings_properties(value)


def _contract(**mapping):
    doc = copy.deepcopy(load_document(CATALOGUE_DIR / "verify-identity.yaml"))
    doc["mappings"] = {"apqc_pcf": mapping}
    return doc


def test_mapping_needs_a_checkable_source():
    with pytest.raises(ValidationFailed):
        Contract.from_dict(_contract(ref="10002"))


def test_mapping_relation_is_constrained():
    with pytest.raises(ValidationFailed):
        Contract.from_dict(_contract(ref="10002", source="https://www.apqc.org/pcf", relation="roughly"))
    Contract.from_dict(_contract(ref="10002", source="https://www.apqc.org/pcf", relation="closest", version="8.0"))


def test_mapping_ref_must_not_be_empty():
    with pytest.raises(ValidationFailed):
        Contract.from_dict(_contract(ref="", source="https://www.apqc.org/pcf"))


def test_process_mappings_pass_through_the_answers_file_without_affecting_ratings():
    plain = evaluate_answers(copy.deepcopy(ANSWERS))
    doc = copy.deepcopy(ANSWERS)
    doc["processes"][0]["mappings"] = {
        "apqc_pcf": {"ref": "10002", "version": "8.0", "source": "https://www.apqc.org/pcf", "relation": "partial"},
        "unmapped_scheme": None,
    }
    assessment, _, _ = convert(Bank.load(), doc)
    assert assessment["processes"][0]["mappings"]["apqc_pcf"]["ref"] == "10002"
    mapped = evaluate_answers(doc)
    assert [p.rating for p in mapped.processes] == [p.rating for p in plain.processes]


def test_bad_process_mapping_is_rejected():
    doc = copy.deepcopy(ANSWERS)
    doc["processes"][0]["mappings"] = {"apqc_pcf": {"ref": "10002"}}
    with pytest.raises(ValidationFailed):
        evaluate_answers(doc)
