# Governance

Asya follows a maintainer-driven governance model.

## Roles

### Maintainers

Maintainers have merge authority and are responsible for the project's
technical direction. See [MAINTAINERS.md](MAINTAINERS.md) for the current list.

Maintainers are expected to:

- Review and merge contributions
- Triage issues and guide contributors
- Participate in architectural decisions
- Uphold the Code of Conduct

### Contributors

Anyone who submits a pull request, files an issue, or participates in
discussions is a contributor. All contributions must follow the
[Developer Certificate of Origin (DCO)](https://developercertificate.org/) by
adding a `Signed-off-by` line to commit messages (`git commit -s`). This is
enforced automatically on pull requests. See
[CONTRIBUTING.md](CONTRIBUTING.md#developer-certificate-of-origin-dco) for
details.

## Decision Process

- **Day-to-day decisions**: Any maintainer can merge PRs that have at least one
  approval and pass CI.
- **Significant changes** (new components, API changes, architectural shifts):
  Require an RFC document and lazy consensus among maintainers (no objection
  within 7 days).
- **Governance changes**: Require explicit approval from all active maintainers.

## Code of Conduct

This project follows the
[Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/).

## Licensing

Asya is licensed under [Apache License 2.0](LICENSE). All contributions must be
made under the same license.
