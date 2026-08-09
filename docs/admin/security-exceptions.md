# Security exceptions

## SEC-2026-001

- Advisory: `CVE-2026-45829` (`PYSEC-2026-311` in pip-audit)
- Component: embedded ChromaDB
- Owner: Bunnyland release operator
- Approved: 2026-07-29
- Expires: 2026-08-28
- Review cadence: every 7 days
- Status: temporary launch exception

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
