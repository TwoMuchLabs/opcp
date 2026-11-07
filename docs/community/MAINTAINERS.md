# Becoming a maintainer

GOVERNANCE.md section 2 says new maintainers are nominated by an existing maintainer after "sustained, substantive contributions" and confirmed by lazy consensus. This page proposes what that means, so the path is visible to everyone and doesn't depend on knowing the founders.

## Three roles

| Role | Can | Becomes one by |
|---|---|---|
| Contributor | Open issues and PRs, review anything | Contributing |
| Reviewer | Be requested for review; their approval counts towards lazy consensus for code, docs and fixtures in an area (for example `conformance/` or the scorecard) | Nomination by a maintainer after about three months of regular, substantive reviews or contributions in that area |
| Maintainer | Merge; steward the specification; vote in disputes | Nomination after about six months as a reviewer, confirmed by lazy consensus of the maintainers |

The durations are guides, not counts to game. What matters is judgement shown in public: reviews that find real problems, fixes that hold up, and specification proposals that survive the RFC process.

## Expectations of maintainers

- Review within the service levels in [ONBOARDING.md](ONBOARDING.md), or say when you can't.
- Never merge your own normative change. Approve others' only after the 14-day period.
- Declare a conflict of interest when reviewing work that affects a product you or your employer sell.

## Stepping back

A maintainer may step back at any time to emeritus status and keep their credit. A maintainer inactive for six months is asked whether they wish to continue, then moved to emeritus by lazy consensus if they don't reply within a month.

## Proposed change to GOVERNANCE.md

Adding the reviewer role, and letting a reviewer's approval count towards lazy consensus in their area, changes GOVERNANCE.md section 2. That needs its own pull request and the maintainers' agreement. Until then, reviewers' approvals are advisory.
