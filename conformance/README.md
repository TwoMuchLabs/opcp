# Conformance fixtures

Machine-readable test cases that any OPCP implementation can run, in any language. They are test data, not specification: the rules they check are in [`spec/`](../spec/), and each fixture names the section it exercises.

## Format

Each fixture is one JSON file:

```json
{
  "id": "SD-10-revisions-differ-gate-true",
  "guarantee": "What protocol rule this case checks, with the spec section.",
  "expected_outcome": "pass | fail | reject",
  "evidence": { "...": "the input document" }
}
```

Outcomes are defined so that implementations do not have to match each other's error messages:

| Outcome | Meaning |
|---|---|
| `pass` | The input is valid and the candidate is promotable. |
| `fail` | The input is valid, and at least one promotion gate correctly blocks promotion. |
| `reject` | The input is not a valid record: it breaks the schema or an invariant, or contradicts itself. |

## Suites

| Directory | Specification | Fixtures |
|---|---|---|
| [`swap-drill/`](swap-drill/) | [`spec/SWAP-DRILL.md`](../spec/SWAP-DRILL.md) | SD-01 to SD-15, covering every case listed in section 8 plus invariant, count and decision consistency |

## Running them

The reference implementation runs every fixture in `tests/test_conformance_fixtures.py`. Another implementation should load each file, evaluate `evidence`, map its result to one of the three outcomes, and compare with `expected_outcome`.

## Adding a fixture

One fixture checks one rule. Change a single thing from a passing record, keep everything else consistent (counts, gates, decision), and state the rule in `guarantee`. A fixture that fails for several reasons cannot show which rule an implementation enforces.
