# Security Policy

## Supported releases

Security fixes are provided for the latest Bunnyland 1.x release. Release candidates are
supported while they are the current published preview. Older prerelease and development
versions should be upgraded before reporting a reproduction.

## Reporting a vulnerability

Report vulnerabilities privately through this repository's GitHub Security Advisory
"Report a vulnerability" form. Do not open a public issue for authentication bypass,
cross-character data exposure, claim or token compromise, secret disclosure, remote code
execution, or denial-of-service findings.

Include the affected version or immutable image digest, deployment shape, reproduction,
impact, and any evidence that can be shared safely. Remove bearer tokens, claim secrets,
private memory text, provider prompts, and player messages from logs before attaching them.

The maintainers will acknowledge the report, reproduce it against a supported release,
coordinate a fix and disclosure, and credit the reporter when requested. If active
exploitation or private-data exposure is suspected, revoke affected credentials, stop the
exposed service, retain redacted audit evidence, and restore only from a verified recovery
point.
