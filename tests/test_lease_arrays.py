"""Context lease inside arrays (red-team R2-01, spec 11.2)."""

import json

import pytest

from test_runtime import CATALOGUE

def _lease_contract(properties):
    from opcp.contract import Contract
    doc = dict(CATALOGUE["verify-identity"].raw)
    doc["input"] = {"type": "object", "properties": properties}
    return Contract.from_dict(doc)


@pytest.mark.parametrize("schema", [
    {"type": "array"},                                                                    # no items schema
    {"type": "array", "contains": {"type": "object", "properties": {"a": {"type": "string"}}}},
    {"type": "array", "prefixItems": [{"type": "object", "properties": {"a": {"type": "string"}}}]},
    {"type": "array", "items": True},
    True,
])
def test_lease_withholds_undeclared_fields_inside_arrays(schema):
    # Red-team round 2: these arrays passed their elements whole, so undeclared nested fields
    # reached the supplier (spec 11.2: "at every level of nesting"; the lease fails closed).
    c = _lease_contract({"xs": schema})
    leased, withheld = c.lease({"xs": [{"a": "ok", "secret": "S"}]})
    assert "S" not in json.dumps(leased), leased
    assert "xs[0].secret" in withheld


def test_lease_prunes_prefix_items_by_position_then_items():
    c = _lease_contract({"pair": {"type": "array",
                                  "prefixItems": [{"type": "object", "properties": {"a": {"type": "string"}}}],
                                  "items": {"type": "object", "properties": {"b": {"type": "string"}}}}})
    leased, withheld = c.lease({"pair": [{"a": "1", "b": "x"}, {"a": "y", "b": "2"}]})
    assert leased == {"pair": [{"a": "1"}, {"b": "2"}]}
    assert withheld == ["pair[0].b", "pair[1].a"]


def test_lease_keeps_scalars_in_arrays_and_withholds_forbidden_elements():
    c = _lease_contract({"tags": {"type": "array"},
                         "fixed": {"type": "array", "prefixItems": [{"type": "string"}], "items": False},
                         "never": False})
    leased, withheld = c.lease({"tags": ["a", "b"], "fixed": ["one", "two"], "never": "x"})
    assert leased == {"tags": ["a", "b"], "fixed": ["one"]}
    assert withheld == ["fixed[1]", "never"]


def test_lease_still_passes_declared_array_items():
    c = _lease_contract({"lines": {"type": "array", "items": {"type": "object", "properties": {"account": {"type": "string"}}}}})
    leased, withheld = c.lease({"lines": [{"account": "1"}, {"account": "2", "memo": "m"}]})
    assert leased == {"lines": [{"account": "1"}, {"account": "2"}]} and withheld == ["lines[1].memo"]
