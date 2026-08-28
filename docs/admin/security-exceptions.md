# Security exceptions

## SEC-2026-001

- Advisories: `CVE-2026-45829` (`PYSEC-2026-311` in pip-audit),
  `CVE-2026-45830`, `CVE-2026-45831`, and `CVE-2026-45833`
- Component: embedded ChromaDB
- Owner: Bunnyland release operator
- Approved: 2026-07-29
- Re-accepted: 2026-08-19
- Expires: 2026-09-18
- Review cadence: every 7 days
- Status: temporary launch exception, re-accepted once

Bunnyland retains ChromaDB because removing it would break the required memory backend. The
exception applies only to the immutable server image digest recorded in
`.scanner-exceptions.yaml` and its embedded `PersistentClient` and `EphemeralClient` use.
Bunnyland does not run or expose a Chroma HTTP server, does not enable `trust_remote_code`,
and accepts collection selection only from ECS memory profiles created by Bunnyland.
Player-provided shared collection values must match those registered on the profile.

Every weekly review must update `last_reviewed_at` in `.scanner-exceptions.yaml`, confirm
the matching `.grype.yaml` rule and guard test still pass, check for an upstream fix, and
record the result in the release validation log. The exception expires automatically; CI
rejects an expired or overdue review. It may not be renewed without a new explicit
acceptance.

Review history:

- 2026-08-15: ChromaDB 1.5.9 remains the latest PyPI release and no upstream fix is
  available. The embedded-only reachability assessment and immutable scanner guard remain
  unchanged.
- 2026-08-19: ChromaDB 1.5.9 is still the latest PyPI release and no upstream fix is
  available. The embedded-only reachability assessment, the matching `.grype.yaml` rule,
  and the guard test are unchanged and passing.
- 2026-08-19: The release operator re-accepted the exception and extended it to
  2026-09-18. The rationale is unchanged: no upstream fix exists, and removing ChromaDB
  would break the required memory backend. This is the single re-acceptance the policy
  above allows; a further extension needs another explicit acceptance. The `.grype.yaml`
  rule matches by advisory and package rather than by image digest, so the suppression
  follows rebuilt images; `image_ref` records the digest the reachability assessment was
  performed against, not a scan filter.
- 2026-08-28: GitHub Advisory Database and NVD still report no patched ChromaDB release.
  The vulnerable pre-authentication HTTP collection-creation path remains unreachable:
  Bunnyland uses only embedded clients, exposes no Chroma HTTP server, and never enables
  remote embedding code. The matching scanner rule and guard test remain unchanged.
- 2026-08-28: The audit database added `CVE-2026-45830`, `CVE-2026-45831`, and
  `CVE-2026-45833`. The first two require Chroma's networked multi-tenant authorization
  surfaces; the third requires authenticated collection updates with a caller-selected
  remote embedding function. Bunnyland runs one embedded in-process tenant, does not enable
  Chroma RBAC or HTTP routes, never accepts embedding-function configuration, and never sets
  `trust_remote_code`. No upstream fix exists. Each advisory now has its own narrow scanner
  entry under this exception's existing expiry and weekly review cadence.
