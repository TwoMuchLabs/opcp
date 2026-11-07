# Open Process Control Plane (OPCP) Specification

**Version:** 0.3.0 (draft)
**Status:** Request for comments
**Authors:** Deepak Waghmare, Shaad Sufi
**Licence:** Apache License 2.0

---

## 1. Abstract

Businesses increasingly run their processes inside vendor platforms and vendor AI agents. When a vendor holds a firm's process logic, its accumulated context and the authority to act, replacing that vendor means rebuilding part of the business. Regulators in several jurisdictions now ask regulated firms to understand this concentration and to hold workable exit plans.

OPCP defines a small set of open, vendor-neutral building blocks that let a business keep three things for itself while renting everything else:

- **Process logic**, held as owned, versioned specifications.
- **Context**, held in the business's own event log and lent to vendors only for the task at hand.
- **Authority**, exercised through one gate that every action passes.

Vendors, internal systems and human teams plug in underneath through **capability contracts**. Every contract belongs to one of seven **archetypes** and every call uses one **envelope**, so adding a vendor, a process or a customer is configuration rather than a bespoke integration.

The specification also defines an **Exit-Readiness Scorecard**, so a firm can measure how dependent each critical process is on its current supplier before adopting anything else.

## 2. Conventions

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT** and **MAY** are to be interpreted as described in [RFC 2119](https://www.rfc-editor.org/rfc/rfc2119).

Sections marked *(informative)* explain or advise and are not requirements.

### 2.1 Versions

OPCP has three version numbers, which change independently.

1. **Specification version.** One version for the normative set: this document, its companion specifications in `spec/` (such as [`SWAP-DRILL.md`](SWAP-DRILL.md)) and the schemas in `schema/`. It is shown in the header of each specification document and changes only through the request-for-comments process in `GOVERNANCE.md`. A minor version adds compatible features. A breaking change requires a new major version. While the major version is 0, a minor version **MAY** include breaking changes, and its release notes **MUST** list them.
2. **Format version.** Every document type carries a format version: `opcp_version` in capability contracts, routes and swap-drill records; `envelope_version` in requests and responses; `scorecard_version` and `answers_version` in scorecard files. A format version is **the specification version in which that document type's schema last changed**. A document type whose schema is unchanged keeps its format version when the specification version moves on. Each schema's `$id` carries its format version.
3. **Implementation version.** Each implementation versions its own releases. An implementation **MUST** state which specification version it implements, and **SHOULD** list the format versions it reads and writes.

An implementation **MUST** reject a document whose format version it does not support, and **MUST NOT** infer a document's meaning from an implementation version.

Format versions defined by specification 0.3.0:

| Document type | Field | Format version |
|---|---|---|
| Capability contract | `opcp_version` | `"0.1"` |
| Route | `opcp_version` | `"0.1"` |
| Request and response envelope | `envelope_version` | `"0.1"` |
| Swap-drill record ([`SWAP-DRILL.md`](SWAP-DRILL.md)) | `opcp_version` | `"0.3"` |
| Scorecard assessment | `scorecard_version` | `"0.1"` |
| Scorecard answers | `answers_version` | `"0.1"` |

*(informative)* The reference implementation's package version is independent: package 0.3.0 implements specification 0.3.0, but a later package release that only fixes code keeps implementing 0.3.0.

## 3. Terminology

- **Business.** The organisation that owns the processes. Also called the *principal*.
- **Process.** A defined piece of work with a goal, an owner and an outcome, such as identity verification during customer onboarding.
- **Step.** One unit of a process that calls exactly one capability.
- **Capability.** A named job a process needs done, such as `verify-identity`, independent of who does it.
- **Archetype.** The interaction shape of a capability (Section 5).
- **Capability contract.** The published definition of a capability: its archetype, inputs, outputs, classification and service levels (Section 6).
- **Supplier.** Whoever fulfils a capability: an external vendor, an internal system or a human team.
- **Adapter.** Software that lets one supplier fulfil one capability contract (Section 8).
- **Envelope.** The standard request and response wrapper for every capability call (Section 7).
- **Route.** The business's rule for which supplier fulfils a capability, and how (Section 9).
- **Authority gate.** The checkpoint that decides whether an action may proceed, and on whose approval (Section 10).
- **Event log.** The business's append-only record of every request, decision and response (Section 11).
- **Context lease.** The subset of the business's data lent to a supplier for one call (Section 11).

## 4. Design principles *(informative)*

1. **Own the nouns, rent the verbs.** The business owns what its processes are, what it knows and who may act. Suppliers provide actions.
2. **Contracts before suppliers.** A process calls a capability, never a vendor.
3. **Exit is a feature.** Every critical capability has a named fallback and a measured time-to-swap.
4. **Context leaves on lease and comes home.**
5. **Every action is reversible or explicitly approved.**
6. **Open formats in the owned layers.** Nothing the business owns is stored in a format only one product can read.

## 5. Capability archetypes

Domains are numerous; interaction shapes are few. Every capability contract **MUST** declare exactly one archetype. An archetype fixes the fields its responses carry in addition to the common envelope.

| Archetype | In → out | Required output fields | Typical examples |
|---|---|---|---|
| `check` | Entity → verdict | `verdict` (`pass`, `fail` or `refer`), `reason_codes` (list) | Sanctions screening, fraud scoring, credit checks, identity verification |
| `extract` | Document or media → structured fields | `fields` (object), `field_confidence` (object, values 0–1) | OCR, document intelligence, transcription, classification |
| `generate` | Context → draft for review | `draft` (string), `review_status` (`pending`, `approved` or `rejected`) | Letters, summaries, reports, code |
| `transact` | Command → state change | `receipt_id` (string), `status` (`completed`, `pending` or `failed`), `compensation` (string) | Payments, ledger postings, bookings |
| `retrieve` | Query → records | `records` (list), `as_of` (timestamp) | Credit bureau, market data, search |
| `notify` | Message → delivery receipt | `message_id` (string), `delivery_status` (`queued`, `sent`, `delivered` or `failed`) | Email, SMS, messaging apps |
| `human_task` | Work item → outcome | `outcome` (string), `assignee_role` (string), `completed_at` (timestamp) | Staff work queues, outsourced operations |

Rules:

1. A response for an archetype **MUST** include its required output fields, in addition to any fields the contract's own output schema requires.
2. A `generate` response **MUST** start with `review_status` set to `pending` unless the contract's authority policy permits unreviewed use.
3. A `transact` response **MUST** state in `compensation` how the effect can be undone or compensated, or `none` if it cannot.
4. *(informative)* The `human_task` archetype treats people and outsourcing providers as suppliers like any other. This is how exception handling, which dominates real processes, fits the same model.

## 6. Capability contracts

A capability contract is a YAML or JSON document that **MUST** validate against [`schema/capability.schema.json`](../schema/capability.schema.json).

### 6.1 Fields

| Field | Required | Meaning |
|---|---|---|
| `opcp_version` | yes | Format version of the capability contract (section 2.1), `"0.1"` in this specification. |
| `id` | yes | Stable identifier in kebab case, e.g. `verify-identity`. |
| `version` | yes | Semantic version of the contract. |
| `name` | yes | Human-readable name. |
| `archetype` | yes | One of the seven archetypes in Section 5. |
| `description` | yes | One or two sentences on what the capability does. |
| `input` | yes | JSON Schema for the request input. Its top-level `properties` define the context lease (Section 11.2). |
| `output` | yes | JSON Schema for the response output. |
| `rclass` | yes | Base Reversibility Class (`R0`–`R4`) of the capability's effect (Section 10). |
| `data_classification` | yes | Highest data classification the input may contain: `public`, `internal`, `confidential` or `restricted`. |
| `evidence_required` | no | `true` if every response must include evidence. Default `true` for `check` and `transact`. |
| `service_level` | no | Target `latency_ms_p95` and `availability`. |
| `mappings` | no | References to external taxonomies, such as `apqc_pcf` and `bian_service_domain`. Each value **MUST** cite its source or be left empty. |
| `examples` | yes | At least one example input used by the conformance suite. |

### 6.2 Versioning

A change that removes or renames a field, tightens a type, or raises `rclass` is breaking and **MUST** increase the major version. Adapters declare the major version they implement.

### 6.3 Canonical data

Contracts **SHOULD** use established industry data standards where they exist, for example ISO 20022 message structures for payments. A contract **MUST NOT** embed a supplier's proprietary identifiers in its required fields.

### 6.4 The two-vendor rule

A capability **SHOULD** enter a shared catalogue only when at least two independent suppliers can fulfil its contract. A capability fulfilled by one supplier **MUST** be marked `single_source: true` in any registry that lists it. In the scorecard (Section 12) it appears as a missing fallback supplier.

## 7. The envelope

Every capability call uses one request envelope and one response envelope, defined in [`schema/envelope.schema.json`](../schema/envelope.schema.json).

### 7.1 Request

| Field | Required | Meaning |
|---|---|---|
| `envelope_version` | yes | Format version of the envelope (section 2.1), `"0.1"` in this specification. |
| `trace_id` | yes | Unique identifier for this call, carried into every log entry. |
| `idempotency_key` | yes | Scoped to the capability and principal. Repeating a request with the same key and input **MUST NOT** repeat its effect; reusing a key with different input **MUST** be refused. A runtime **MUST NOT** replay a rejected or failed response, so that a retry after approval or recovery can succeed. |
| `capability` | yes | `{id, version}` of the contract. |
| `process` | yes | `{id, step}` that made the call. |
| `principal` | yes | Who the call acts for: a user, team or system identity. |
| `input` | yes | The leased input (Section 11.2). |
| `data_classification` | yes | Classification of this input. |
| `residency` | no | Regions in which the input may be processed, e.g. `["SG"]`. Omitted means no restriction; an empty list permits no region. |
| `segment` | no | Routing segment, e.g. country, risk band or product. |
| `lease_expires_at` | no | When the supplier must discard the input. |

### 7.2 Response

| Field | Required | Meaning |
|---|---|---|
| `envelope_version` | yes | Format version of the envelope (section 2.1), `"0.1"` in this specification. |
| `trace_id` | yes | Same as the request. |
| `status` | yes | `ok`, `failed`, `rejected` (stopped by the gate) or `escalated` (handed to a human). |
| `output` | when `ok` | Output that validates against the contract and its archetype (Section 5). |
| `evidence` | when required | List of evidence items, each `{type, reference}`. |
| `confidence` | no | 0 to 1, where the supplier can state one. |
| `cost` | no | `{amount, currency}`. |
| `latency_ms` | yes | Elapsed time of the call. |
| `supplier` | yes when `ok` or `escalated` | `{id, adapter_version}`. |
| `rclass` | yes | Reversibility Class applied by the gate. |
| `route` | yes | `{mode, reason}`: why this supplier was chosen. |

## 8. Adapters

An adapter connects one supplier to one capability contract.

1. An adapter **MUST** produce outputs that validate against the contract and its archetype.
2. An adapter **MUST** declare a **supplier profile**: supplier identifier, supplier kind (`vendor`, `internal` or `human`), the third-party register reference (if the supplier is external), contract end date, permitted data classifications, processing regions, the highest Reversibility Class it is authorised to perform, and whether it has passed conformance.
3. An adapter **MUST** honour idempotency keys.
4. An adapter **MUST NOT** retain leased input beyond `lease_expires_at`, or beyond the call if none is given, except where the supplier contract explicitly permits it and the permission is recorded in the supplier profile.
5. An adapter **SHOULD** report cost and confidence.
6. Adapters are shared assets. A deployment **SHOULD** configure existing adapters rather than write new ones for each process.

## 9. Routing

A route decides which supplier fulfils a capability for a given request. Routes are declarative documents that **MUST** validate against [`schema/route.schema.json`](../schema/route.schema.json), and **MUST** be versioned and approved by a second person before taking effect (maker-checker).

### 9.1 Stage 1: eligibility

For every request, a runtime **MUST** exclude any candidate supplier that fails any of these filters. Eligibility filters are never traded off against scores.

1. The supplier is approved in the business's third-party register.
2. The supplier's contract is active on the date of the call.
3. The adapter has passed conformance for the contract's major version.
4. The supplier is permitted to process the request's data classification.
5. The supplier processes data only in regions the request permits.
6. The Reversibility Class applied by the authority gate, including any deployment override, is within the supplier's authorised maximum.
7. The supplier is healthy and has capacity.

If no candidate is eligible, the runtime **MUST** return `status: failed` with the exclusion reasons, or escalate to the route's escalation supplier if one is configured.

### 9.2 Stage 2: selection

Among eligible suppliers, a route selects according to its mode. Where a mode uses scores, a runtime **SHOULD** combine:

- quality measured on the business's own data, by segment;
- cost per call;
- latency against the contract's service level;
- commercial commitments, such as volume tiers.

### 9.3 Modes

| Mode | Behaviour | When to use it *(informative)* |
|---|---|---|
| `pinned` | Use the primary supplier; on failure, try fallbacks in order. | The default for regulated work, where each supplier is a third-party arrangement and changes are deliberate. |
| `segmented` | Try the request segment's suppliers first, e.g. by country or risk band, then the default candidates as fallbacks. | Different suppliers by market, language or product. |
| `cascade` | Try suppliers in order; move to the next when confidence is below a threshold. The last step **SHOULD** be a human supplier. | Identity checks and document extraction. |
| `weighted` | Split traffic by weight. | Migrations and shadow drills. |
| `best_score` | Pick the highest selection score per call. | Low-risk `generate` and `retrieve` work only. A runtime **MUST NOT** use this mode for capabilities above R1. |

Supplier kind is independent of archetype. A human team **MAY** fulfil any contract, such as a reviewer team fulfilling `verify-identity` as the last step of a cascade. The `human_task` archetype is for work that is inherently human, where the contract itself describes a work item and an outcome.

### 9.4 Concentration limits

A business **MAY** set a concentration limit: the largest share of its critical processes that any one supplier may fulfil as primary. A runtime or registry **MUST** reject a route change that would breach the limit, unless the breach is recorded as an approved exception.

## 10. Authority gate

Every capability call **MUST** pass the authority gate before any supplier is invoked.

1. The gate uses the Reversibility Classes R0–R4 defined in [*Reversibility Classes for Agent Actions*](https://github.com/TwoMuchLabs/reversibility-classes) (version 0.1). A contract's `rclass` is the base class; a deployment **MAY** raise it, and **MAY** lower it only as that specification permits.
2. A call to a capability with no contract **MUST** be treated as R4 (fail closed).
3. **Leasing data to a supplier is not, by itself, a disclosure for classification purposes.** Lending input to an approved supplier under contract is governed by the eligibility filters (Section 9.1) and the context lease (Section 11.2). A contract's `rclass` describes the capability's intended effect on the world: a `check` that only reads and returns a verdict is R0, while a `notify` that delivers a message to a customer is R4. A deployment that treats a supplier as outside its control **MUST** raise the class to R4 for that supplier. See open question 6.
4. The default policy follows Section 8 of that specification:

| Class | Default decision |
|---|---|
| R0 | Allow. |
| R1 | Allow, then notify. |
| R2 | Require approval, or allow within a pre-approved budget. |
| R3 | Require explicit approval for each call. |
| R4 | Never autonomous; require approval, and a second approver for high-stakes disclosures. |

5. Every step performed by an AI agent **MUST** name the accountable human role in the process specification, and the gate **MUST** record it with each decision. *(informative)* The reference runtime requires an accountable role on every call by default, which is stricter than this rule.
6. Every gate decision **MUST** be written to the event log, including the class, the decision, who approved and why.

## 11. Context home

### 11.1 Event log

The business's event log is its system of record for the control plane. A runtime **MUST** append, for every call: the request (with input reduced to field names unless the deployment opts to store values), the gate decision, the route decision with any exclusion reasons, and the response. Entries **MUST NOT** be modified after writing. The log **MUST** be exportable in an open format such as JSON Lines.

### 11.2 Context lease

A supplier receives only the input fields declared in the contract's input schema, at every level of nesting. A runtime **MUST** remove any other fields before invoking an adapter, and **MUST** record which fields were lent and which were withheld. The lease fails closed: an object is passed whole only when its schema explicitly sets `additionalProperties: true`, and a runtime that cannot determine which parts of a field are declared (for example, under `anyOf` or `$ref`) **MUST** withhold that field. Where the deployment does not store input values, error messages written to the log **MUST NOT** contain them either.

### 11.3 Learning stays home

Corrections, reviewer decisions and evaluation results **SHOULD** be written to the event log, so that a replacement supplier can be evaluated on the business's own history. *(informative)* Supplier-specific artefacts, such as embeddings or fine-tuned models, cannot usually move between suppliers and will need rebuilding.

## 12. Exit-Readiness Scorecard

The scorecard measures how dependent each critical process is on its current supplier. Assessments **MUST** validate against [`schema/scorecard.schema.json`](../schema/scorecard.schema.json).

### 12.1 Measures

| Measure | Values | Ready | Partial | Locked |
|---|---|---|---|---|
| Logic ownership | Where rules and steps live | `owned` | `shared` | `vendor_held` |
| Context residency | Can learned context leave in usable form | `exportable` | `partial` | `trapped` |
| Authority | Whose permission model governs actions | `ours` | `vendor` | `none` |
| Lock-in debt | Count of supplier-only dependencies | 0 | up to a threshold (default 3) | above it |
| Contract exit terms | Data return, termination assistance, notice period | All present, notice within tolerance | Data return present; termination assistance missing or notice beyond tolerance | No data return |
| Time-to-swap | Estimated or proven days | Within the business's tolerance | Up to twice the tolerance | Beyond twice the tolerance |
| Fallback | A second supplier identified | Yes | — | No (single source) |

### 12.2 Weakest link

A process's overall rating is its **worst** measure. *(informative)* An exit fails at its weakest point; averaging would hide exactly the dependency the scorecard exists to find.

### 12.3 Time-to-swap

Time-to-swap is the elapsed days from a decision to replace the supplier behind a capability to the replacement running in production at equal or better quality, with no customer-facing disruption. It **MUST** be reported in three parts, contracting, onboarding and technical cutover, and with a confidence of either `estimated` or `proven`. Only a completed swap drill makes it `proven`, and a `proven` figure **MUST** carry the drill date.

### 12.4 Portfolio concentration

Across critical processes, the scorecard **MUST** report the share for which each supplier is primary, and flag any supplier above the business's concentration limit.

### 12.5 Privacy

A scorecard implementation **MUST** run without network access and **MUST NOT** send any assessment data outside the machine on which it runs.

### 12.6 Standard question bank

Scorecard inputs **SHOULD** be collected with the OPCP question bank ([`questions/exit-readiness.yaml`](../questions/exit-readiness.yaml)), so that answers are comparable across processes, firms and years. Answers are recorded in an answers file that **MUST** validate against [`schema/answers.schema.json`](../schema/answers.schema.json).

1. Every question has a stable identifier, such as `ERS-LOG-01`. An identifier **MUST NOT** be reused for a question with a different meaning.
2. Choice questions have closed options, each with a definition of what qualifies.
3. Every question names the role best placed to answer it.
4. A short triage section decides whether a process is critical. A process is critical if any triage answer is Yes. Processes triaged as not critical **MAY** be left unassessed and are then listed, not rated.
5. Consistency rules flag combinations of answers that contradict each other. Flags do not change ratings; they ask for a second look.
6. Any channel (an offline form, a spreadsheet, a workshop, an API) **MUST** record answers by question identifier, so every channel produces the same answers file.

### 12.7 Evidence levels

Every rated answer carries an evidence level:

| Level | Meaning |
|---|---|
| `declared` | Someone with knowledge of the process states it. |
| `documented` | A named record supports it, such as a contract clause, configuration export or register entry. |
| `tested` | It was demonstrated in practice within the last 12 months, such as a completed export or swap drill. |

An answer marked `documented` or `tested` **MUST** name its record. A measure's evidence level is that of its **weakest** supporting answer. Reports **MUST** show each measure's evidence level next to its rating, and the share of rated answers backed by a record or a test.

### 12.8 References and status

Each question **MAY** cite the published obligations and principles it relates to, by source and locator, from a library of sources ([`references/frameworks.yaml`](../references/frameworks.yaml)) that records how each was checked. Reports **MUST**:

- show references as "relates to", never as evidence of compliance;
- state that the report is a self-assessment against a published method and not a certification;
- show who prepared the assessment and whether it was independently reviewed.

The research behind each measure is summarised in [`docs/EVIDENCE.md`](../docs/EVIDENCE.md).

## 13. Conformance

- **Adapter conformance.** For each contract example, the adapter's output validates against the contract output schema and the archetype's required fields; evidence is present where required; and a repeated idempotency key does not repeat the effect.
- **Runtime conformance.** The runtime applies the authority gate before any supplier call, enforces every eligibility filter, enforces the context lease at every depth, refuses `best_score` above R1, fails closed for unknown capabilities, honours and scopes idempotency keys, and writes every gate decision to the event log.

The reference implementation includes runners for both (`opcp.conformance.check_adapter` and `opcp.conformance.check_runtime`).

## 14. Security and privacy considerations

- Supplier profiles and routes are security-relevant configuration and **SHOULD** be protected by the same change controls as production code.
- The event log may contain personal data. Deployments **SHOULD** store field names only, unless they have a lawful basis to store values.
- Confidence values reported by suppliers are claims, not measurements. Selection scores **SHOULD** rely on the business's own evaluation results.

## 15. Relationship to other work *(informative)*

- **Reversibility Classes for Agent Actions** supplies the R0–R4 vocabulary used by the authority gate.
- **The APQC Process Classification Framework** and, for banks, **BIAN service domains** are suitable taxonomies for organising process registries and capability catalogues.
- **The Model Context Protocol (MCP)** is a suitable transport for adapters that wrap AI tools; OPCP contracts describe *what* a capability does, independent of transport.
- **Regulation.** The scorecard is designed to support, not replace, obligations such as the EU Digital Operational Resilience Act, under which European supervisors [designated critical ICT third-party providers](https://www.esma.europa.eu/press-news/esma-news/european-supervisory-authorities-designate-critical-ict-third-party-providers) in November 2025; APRA's Prudential Standard CPS 230 in Australia, which commenced on 1 July 2025; and the Monetary Authority of Singapore's Guidelines on Third-Party Risk Management, [proposed for consultation in March 2026](https://www.mondaq.com/financial-services/1809374/extending-the-regulatory-perimeter-beyond-outsourcing-mas-proposed-third-party-risk-management-guidelines-and-lessons-from-australias-cps-230). Nothing in this specification is legal or regulatory advice.

## 16. Open questions

1. Should contracts support argument-conditional Reversibility Classes in v0.1, as the Reversibility Classes specification does for tools, or defer to v0.2?
2. What is the minimum evidence format that auditors will accept for `check` and `transact` responses?
3. How should a `human_task` supplier report confidence?
4. Should the scorecard include an operational baseline (cycle time, straight-through rate, cost per case, exception rate) as a required section, or keep it optional as in v0.1?
5. How should process variants by country or legal entity be expressed in a process specification?
6. Rule 10.3 treats data leased to an approved, contracted supplier as governed by eligibility rather than as a disclosure. Is that consistent with the disclosure definition in *Reversibility Classes for Agent Actions*, or should that specification add a defined category for contracted processors?
