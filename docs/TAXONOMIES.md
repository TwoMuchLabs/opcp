# Industry taxonomies and standards

OPCP doesn't invent its own process taxonomy. Capability contracts and processes carry **mappings**: pointers to established schemes, so a firm can line OPCP up with the process inventory, capability map or architecture it already keeps. This page explains which schemes OPCP uses, how, and what their licences allow.

> **Not legal advice.** Licence positions below were read from each publisher's own terms in October 2026. Where a term could not be read first-hand it is marked *unverified*. Check the current terms before you bundle anything.

## How a mapping looks

```yaml
mappings:
  bian_service_domain:
    ref: Party Lifecycle Management     # the identifier or name in the external scheme
    version: "14.0.0"                   # the release it refers to
    relation: partial                   # exact, closest or partial (closest if omitted)
    source: https://github.com/bian-official/public/blob/b58bf4c2c300dd018afc084e9bb24b7adaaa3500/release14.0.0/semantic-apis/oas3%20/yamls/PartyLifecycleManagement.yaml
    note: Identity verification is one of the checks this service domain covers.
  apqc_pcf: null                        # not mapped yet
```

The rules:

- Every mapping gives a `ref` and a `source` it can be checked against, or it is `null`.
- A mapping is a pointer, not a copy: OPCP never needs the external scheme's text to work.
- Mappings are informative. Routing, the authority gate and the scorecard ignore them.

Processes in a scorecard answers file can carry the same `mappings` block. Use this to record, for example, the APQC element a process corresponds to in your own process inventory.

## Schemes OPCP uses

| Scheme | Used for | Licence position | How OPCP uses it |
|---|---|---|---|
| **APQC Process Classification Framework (PCF)**, cross-industry v8.0 (Feb 2026); banking v7.2.2 (Mar 2025) | The process registry: what each process is | Free to use, copy, modify and redistribute, provided every copy carries APQC's attribution notice (wording read in v7.4). APQC changed the licence wording in later versions: read the notice inside the version you download. "PCF" is a registered mark. | Mapping key: the five-digit **element ID**, which APQC keeps stable when names change, plus the PCF version. OPCP ships no PCF text today. |
| **BIAN Service Landscape**, v14.0 (Feb 2026) | The banking capability catalogue: which part of a bank a capability serves | BIAN's semantic API files on GitHub (`bian-official/public`) are Apache 2.0. The landscape website and PDFs are "All rights reserved". | Mapping key: the **service domain name** and release. Catalogue entries map to v14.0, and each `source` is a permalink to that service domain's semantic API file in `release14.0.0/semantic-apis/` (the folder BIAN names `oas3 `, with a trailing space, hence `oas3%20` in the links). |
| **ISO 20022** | `transact` capabilities that move money | Free to use and reproduce under ISO 20022's terms of use. | Mapping key: message identifiers such as `pacs.008`. |
| **BPMN 2.0.2, DMN** (OMG) | Importing process models into a registry; decision tables behind `check` steps | Open specifications for anyone to implement (*unverified*). | Planned: BPMN import with an `opcp:` extension namespace for archetype, contract and reversibility class. |
| **OCEL 2.0** | Exporting the event log to process-mining tools | Published specification; states no licence (*check before bundling schemas*). | `opcp ocel` exports the event log as OCEL 2.0 JSON, since 0.3.0; see [PROCESS-MINING.md](PROCESS-MINING.md). |
| **CloudEvents 1.0** (CNCF) | A wire format for log and routing events | Apache 2.0 (*unverified*). | Under consideration. |

## Schemes OPCP refers to but never copies

These can appear as mapping keys if a firm uses them, but their content must not be bundled into OPCP:

| Scheme | Why not |
|---|---|
| ASCM SCOR | CC BY-NC-ND 4.0: no commercial use and no modification. |
| TM Forum eTOM / ODA | Member terms (*unverified*). TM Forum's Open APIs are moving to Apache 2.0, so they may be usable. |
| ACORD (insurance) | Member-only standards. |
| The Open Group: TOGAF, ArchiMate, O-AA | Free only for non-commercial use. |
| ITIL, ISO 20000 | Proprietary or paid publications. |
| Consulting firms' process models (for example KPMG Powered Enterprise) | Proprietary. Firms are welcome to contribute their own mapping tables under Apache 2.0. |

## Tools to keep out of the Apache-2.0 core

- **PM4Py** (process mining) is AGPL-3.0. Use it as a separately installed plugin that reads OPCP's exported event log, never as a dependency of the core package.
- **Camunda 8** needs a paid licence to run self-managed in production. Execution engines such as Apache KIE, Temporal, Conductor or Flowable can sit behind capability contracts instead. Check each one's licence first.

## Contributing a mapping

1. Add the mapping to the capability contract or process, with a `source` someone else can check: link the item itself, at a fixed release or commit, not a folder or a moving branch.
2. Choose `relation` honestly. Most mappings are `closest` or `partial`, and that is fine.
3. Don't paste the external scheme's descriptions or diagrams into OPCP. The identifier and a short note in your own words are enough.
