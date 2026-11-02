# Governance

OPCP exists so that businesses do not have to depend on any single vendor for how they run. That promise would be hollow if the project itself could become a dependency someone controls. This document sets out the commitments that keep it open, and how decisions are made.

## 1. Commitments that keep the project open

These commitments are deliberately hard to reverse.

1. **One permissive licence for the project's own material.** The specification, schemas, catalogue and code are licensed under the [Apache License 2.0](LICENSE). Apache 2.0 includes a patent licence from each contributor covering their contributions. Whether that also protects independent implementations of the specification is a known open question for specification projects; before version 1.0 the maintainers will decide whether the specification should move to a licence designed for specifications, such as the Community Specification License. Material the project references from elsewhere, such as the Reversibility Classes, keeps its own licence (see [NOTICE](NOTICE)).
2. **No contributor licence agreement.** Contributions are accepted under the Developer Certificate of Origin (see [CONTRIBUTING.md](CONTRIBUTING.md)). Contributors keep their copyright. Because no single party holds all the rights, no single party can relicense the project under more restrictive terms.
3. **Upstream first.** Any paid distribution, support or certification offered by the maintainers is built from this repository. Features are never removed from the open project to make a paid edition more attractive.
4. **The specification is independent of any implementation.** The reference runtime is one implementation. Conformance is defined by public test suites that any other implementation can pass.
5. **Exit applies to us too.** Any OPCP-based distribution offered by the maintainers will let its users move to the upstream project, or to another conformant implementation, without losing their process registry, contracts, routes or event history. The project asks every other distributor to make the same commitment.

## 2. Roles

- **Contributors** propose changes through pull requests or issues.
- **Maintainers** review and merge changes, and steward the specification. The initial maintainers are:
  - Deepak Waghmare
  - Shaad Sufi
- **Specification editors** are the maintainers listed as authors in [`spec/SPEC.md`](spec/SPEC.md).

New maintainers are nominated by an existing maintainer after sustained, substantive contributions, and confirmed by lazy consensus of the maintainers.

## 3. How decisions are made

- **Code changes** are merged by lazy consensus: a maintainer approves, and no maintainer objects within a reasonable review period.
- **Specification changes** follow a request-for-comments process. A pull request that changes `spec/` or `schema/` stays open for at least 14 days before merging, so that implementers can respond.
- **Breaking changes** to a published contract or schema require a new major version and a migration note.
- **Disputes** that consensus cannot resolve are decided by a simple majority of maintainers.

## 4. Organisational diversity

A project with maintainers from only one organisation is itself a concentration risk. The goal before version 1.0 is that **no single organisation employs more than half of the maintainers**.

## 5. Path to a neutral foundation

The founders intend to contribute the specification, the code and the project name to a neutral open-source foundation once maintainers from at least three organisations are active. A foundation focused on financial services, such as [FINOS](https://www.finos.org/), is a candidate, because the first adopters are expected to be regulated financial institutions. The choice will be made in public, through the specification process above.

## 6. Code of conduct

The project follows the [Contributor Covenant, version 2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

## 7. Open items before the first public release

- [x] Security contact: hello@twomuchlabs.com (see [SECURITY.md](SECURITY.md))
- [ ] Decision on a specification-specific licence (see section 1.1)
- [ ] Publication of the package on PyPI
- [x] Project name: Open Process Control Plane (OPCP). Use the full name first; "OPCP" is also used by an unrelated OVHcloud product.
- [ ] Formal trademark search for the name
- [x] Public repository: https://github.com/TwoMuchLabs/opcp
