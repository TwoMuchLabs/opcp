# Running an OPCP pilot

A pilot lasts six weeks. The firm scores three critical processes, rehearses one supplier swap, and finishes with a one-hour readout. The firm keeps its data the whole time: the form runs offline, and OPCP maintainers see only what the firm chooses to share.

This guide is for the person running the pilot inside the firm. It is usually someone in third-party risk, operational resilience or the COO's office.

## What the firm gets

- **A report per process.** A one-page Exit-Readiness report for each process, with a portfolio view of supplier concentration. Every rating traces to the answers, the evidence grade and the regulatory clauses behind it.
- **A proven figure.** At least one time-to-swap backed by a rehearsal rather than an estimate.
- **A say in the framework.** Named, or anonymous, co-authorship of the published case study, and early input into version 1.0 of the questions.

## Before week 1

1. **Name a pilot lead** and a sponsor at head-of-function level or above.
2. **Pick three critical processes** that each depend mainly on one outside supplier. A useful mix:
   - one the firm thinks is locked in
   - one it thinks is fine
   - one where it is not sure

   Identity verification, sanctions screening, document processing, payments and customer notifications are typical.
3. **Name one owner per process.** They gather answers from the other roles.
4. **Agree what may be shared** with the OPCP maintainers. The default is nothing but feedback on the questions. A mutual NDA is available if the firm wants to share results.

## Week by week

| Week | What happens | Who | Output |
|---|---|---|---|
| 1 | Kick-off, 45 minutes. Run `opcp scorecard form`, and send the form to the process owners. Answer the three triage questions per process. | Pilot lead, process owners | Three processes confirmed as critical |
| 1–3 | Owners answer the remaining questions with colleagues. Each question names the role best placed to answer it. Attach evidence references (a contract clause, a register entry, a test report). | Process owner; procurement or legal; technology; risk | Three answers files |
| 3 | Run `opcp scorecard run answers.json -o report.html`. Review the consistency flags and fix any contradictory answers. | Pilot lead | Draft reports |
| 3–5 | Rehearse one swap on the most suitable process ([SWAP-DRILL.md](SWAP-DRILL.md)). | Technology, process owner, risk | Drill record; updated answers |
| 5 | Second-line review of the answers and evidence grades. Record the reviewer in `reviewed_by`. | Risk or compliance | Reviewed reports |
| 6 | Readout, 60 minutes (agenda below), then the feedback questions. | Sponsor, owners, risk | Decisions and feedback |

### Who answers what

| Role | Questions |
|---|---|
| Process owner | TRI-01, LOG-01, AUT-02, OPS-01 to OPS-03 |
| Procurement or legal | DEP-02, CON-01 to CON-05, EXT-01 |
| Technology or architecture | LOG-02, DAT-01, AUT-01, DEP-01, EXT-03 |
| Risk or compliance | TRI-02, TRI-03, EXT-02, EXT-04, and review of the evidence grades |

### Evidence: aim higher than "declared"

An answer is **Declared** when someone says so, **Documented** when it points to a named record, and **Tested** when it was demonstrated in the last 12 months. Each measure shows its weakest evidence. Encourage owners to cite a record for every contract answer, because the contract is usually on file already. Encourage them to test at least one data export.

## Readout agenda (60 minutes)

Prepare the pack with `opcp scorecard readout answers.json -o readout.html`, and print it to PDF. It puts these on two pages: where each process stands, the decisions for the sponsor, and each contract's last day to give notice.

1. **The portfolio view (10 minutes).** How many processes are locked, partial or ready, and which supplier is primary for how many of them.
2. **The weakest link (15 minutes).** The worst-rated process: which measure caused the rating, and what the report recommends.
3. **The drill (15 minutes).** What was rehearsed, the measured days against the estimate, and what surprised people.
4. **Decisions (15 minutes).** Which contract renewals to use as leverage, which rules to bring back in-house, and which second supplier to qualify.
5. **Next steps (5 minutes).** Whether to extend to more processes, and the case-study terms.

## Feedback the maintainers ask for

1. Which questions were hard to answer, and why: unclear wording, missing data, or the wrong respondent?
2. Which answers did the evidence levels change, compared with what people first said?
3. Did any rating feel wrong? Which measure, and what should it have been?
4. How many hours did each process take to answer, in total across all roles?
5. Which register, GRC or third-party risk system would you want results exported to?
6. What would make this usable without a pilot lead to drive it?

Send feedback to hello@twomuchlabs.com or open an issue on the repository. Leave out anything confidential.

## Ground rules

- **Not an audit or certification.** The scorecard is a self-assessment against a published method, and every report says so.
- **No fees and no procurement.** The tool is free and open source under Apache 2.0.
- **Firm-controlled publicity.** The firm decides whether, and how, it is named in any case study.
