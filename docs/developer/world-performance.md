# World-scale performance baseline

This report records the synthetic ECS scaling baseline measured on 2026-07-15. It focuses
on engine operations and deliberately does not duplicate REST, WebSocket, or MCP endpoint
and payload documentation.

## Method and environment

`scripts/benchmark-world full` constructed deterministic worlds at powers of ten from one
through one million total entities and total unique edges. It ran all 66 feasible
entity/edge/topology points where `edges ≤ entities × (entities − 1)`; impossible pairs are
recorded in the generated analysis instead of being synthesized with artificial edge
types or self-relationships. Every point ran with both balanced and source-concentrated
edges. The 16 infeasible power-of-ten pairs include every one-entity case because an edge
always has two distinct endpoints.

The measured server base was `de8c787` plus this benchmark working tree, using CPython
3.12.13 and the pinned Relics revision on 64-bit Linux with 16 logical CPUs. The harness is
single-threaded except that allocation-heavy serialization and persistence measurements
run in forked children so their allocator arenas do not contaminate the next point. The
timed operation begins after the fork; fork time is not included.

The harness does not change the server mutation path. In particular, it adds no world
copy, frozen compatibility view, or rollback snapshot to ordinary mutations. Fork/COW and
mirrored representations below are persistence-only alternatives, not gameplay write
strategies.

The generated `results.jsonl` and `summary.csv` contain every operation sample.
`points.csv` has one row per matrix point, with median milliseconds and live RSS, and
`analysis.json` contains slopes, failures, and gate decisions. The complete run produced
1,320 measurements with no failures or worker crashes.

## Results

This table shows the densest feasible edge point for each entity power. Latencies are
medians in milliseconds; RSS is the live parent world after edge construction. Tiny-world
save latency is dominated by checksum and `fsync` overhead.

| Entities | Edges | Topology | RSS GiB | Idle tick | High-degree mutation | Serialize | Save | Load |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10 | 10 | balanced | 0.05 | 0.060 | 0.012 | 0.245 | 28.013 | 1.672 |
| 10 | 10 | concentrated | 0.05 | 0.060 | 0.022 | 0.456 | 37.882 | 2.618 |
| 100 | 1,000 | balanced | 0.05 | 0.080 | 0.039 | 2.199 | 43.207 | 8.072 |
| 100 | 1,000 | concentrated | 0.05 | 0.085 | 0.141 | 2.108 | 43.320 | 9.615 |
| 1,000 | 100,000 | balanced | 0.08 | 0.322 | 0.303 | 295.638 | 687.159 | 941.660 |
| 1,000 | 100,000 | concentrated | 0.08 | 0.325 | 1.486 | 270.766 | 683.689 | 916.313 |
| 10,000 | 1,000,000 | balanced | 0.38 | 4.484 | 0.323 | 2,732.177 | 6,463.095 | 10,121.343 |
| 10,000 | 1,000,000 | concentrated | 0.36 | 4.875 | 22.147 | 3,014.186 | 6,176.809 | 9,539.619 |
| 100,000 | 1,000,000 | balanced | 0.52 | 96.452 | 0.039 | 3,460.810 | 8,050.249 | 12,786.211 |
| 100,000 | 1,000,000 | concentrated | 0.49 | 99.119 | 243.753 | 4,009.978 | 7,332.473 | 11,187.045 |
| 1,000,000 | 1,000,000 | balanced | 2.03 | 1,220.064 | 0.013 | 13,525.241 | 18,672.818 | 31,541.799 |
| 1,000,000 | 1,000,000 | concentrated | 1.67 | 1,190.366 | 2,802.964 | 13,700.244 | 15,636.477 | 24,630.812 |

At the million-entity/million-edge point, the ordinary bounded paths remained strong:
point lookup was below one microsecond, a singleton component query was about one
microsecond, low-degree component mutation was 9–11 microseconds, edge add/remove was
24–25 microseconds, room projection was 23–24 microseconds, and character projection was
74–85 microseconds. A dense indexed query and full iteration were both about 1.1–1.2
seconds, which is linear and expected for returning one million records.

One million entities without the edge set occupied about 0.96 GB and took about six
seconds to construct. Adding one million edges took 4.8–6.0 seconds. Balanced edges used
about 2.03 GiB live versus 1.67 GiB for concentrated edges because the balanced case creates
per-source relationship dictionaries on many more entities. Persistence peak RSS reached
about 6.55 GB while loading the balanced million/million snapshot.

Measured log-log slopes confirmed the intended classes: full validation was 1.04–1.05,
full iteration and dense query were 1.13–1.15, and edge construction was 0.88–0.92. Point
lookup, singleton queries, low-degree mutation, and local projections remained effectively
flat.

## Problematic performance areas

1. **Resolved: idle ticks scanned unrelated entities.** The baseline idle tick grew with
   an exponent of 0.91–0.92 and reached about 1.2 seconds at one million entities.
   Profiling showed the Relics system executor spending nearly the whole tick in query
   execution because `with_any` does not seed candidates from component indexes.
   Action/Focus regeneration was split into independent systems whose `with_all` queries
   use the Action Points and Focus Points indexes directly. The post-fix smoke matrix was
   flat through 10,000 entities (slopes -0.009 and -0.002), with an idle tick around 54
   microseconds at that tier. The CI gate no longer permits the old linear scaling limit.
   An audit found no other registered ECS system using `with_any` or a combined A-or-B
   query; future systems should likewise prefer independent indexed systems when their
   effects are independent.

2. **Exact graph checks materialize the full adjacency list.** A fully bound graph query
   was flat on balanced worlds but grew with concentrated degree at slope 0.86, reaching
   about 828 ms for a million-edge source. The profile placed essentially all time in
   `World._get_relationships`. The immediate option is to compile a bound source/target
   edge term to the keyed `has_relationship(edge_type, target)` lookup. Unbound traversal
   still needs enumeration.

3. **Mutation validation expands every neighbor regardless of operation type.** Updating
   one unrelated component on a million-degree entity took about 2.80 seconds, while the
   same update on a low-degree entity took about 11 microseconds. The write-set validator
   expands all incoming and outgoing neighbors, then checks each neighbor. The option is
   operation-aware invariant scope: component-only writes validate the touched entity and
   only edge/component invariants they can affect; containment/control edge mutations add
   the endpoints and the specific bounded path needed by their invariant. This must not
   weaken explicit full-world diagnostics.

4. **Relationship enumeration always allocates a list.** Enumerating a million outgoing
   relationships took about 808 ms and scales linearly with degree. That is expected when
   every edge is required, but it is wasteful for existence checks, early-exit searches,
   and streaming consumers. Options are keyed lookup APIs for exact targets and iterator
   or view APIs for genuine traversal.

5. **Persistence blocks the server loop and materializes a full second representation.**
   Autosave runs synchronously after a tick, checkpoint saves can run inside the actor
   command phase, and administrative saves are also synchronous. At million/million scale,
   serialization took 13.5–13.7 seconds, save took 15.6–18.7 seconds, and load took
   24.6–31.5 seconds. The server is not necessarily holding `WorldActor._lock` for every
   save surface, but synchronous traversal blocks the event loop and prevents gameplay.

   The main alternatives are:

   - fork/COW at a tick boundary and serialize in the child; this is the smallest Linux
     experiment, but mutated pages increase memory and forking a process with threads or
     native libraries needs careful review;
   - a long-lived persistence process with a normalized in-memory mirror, which uses less
     memory than a second Relics runtime but still duplicates authoritative payloads;
   - a disk-backed normalized mirror, such as SQLite owned by the persistence process,
     which reduces RAM at the cost of making incremental storage part of the durability
     design;
   - versioned/COW Relics storage, which gives clean immutable roots but is a larger engine
     redesign.

   For either mirror, committed plans and direct fail-stop phases must emit ordered dirty
   entity/edge records. The worker acknowledges a monotonic commit sequence; a checkpoint
   names a target sequence and is complete only after the worker has applied through it,
   written and checksummed the snapshot, and returned its epoch. Restart loads the last
   checkpoint and replays the bounded journal after that sequence. Whole dirty entity
   records are preferable to field-level patches, and repeated dirties may be coalesced.
   None of these designs permits a full-world copy in the mutation path.

6. **Full serialization materializes and sorts the complete response.** The 100,000-scale
   profile was dominated by per-entity serialization/export, recursive JSON conversion,
   and sorting all entity handles. This is correct for an administrative snapshot but
   creates large transient structures. Streaming encoders or the normalized persistence
   mirror can reduce peak duplication; ordinary play projections should remain local and
   must not reuse the full serializer.

7. **Full invariant diagnostics are several seconds at the largest scale.** Explicit full
   validation took 2.95–3.37 seconds at million/million scale. Its linear behavior is
   expected and acceptable for load, persistence verification, tests, and administrative
   diagnostics, but it must stay out of ordinary ticks, event delivery, and fixed-write
   mutations.

## Concurrency options

The baseline is intentionally one actor on one core. Safe early parallelism is independent
worlds in separate processes, plus persistence, reporting, and other read-only analytics
against isolated snapshots or mirrors. Parallelizing systems within one authoritative
world is only safe when their reads are from one fixed epoch and their writes return as
ordered mutation plans to the actor. Partitioning one live world across workers would
require ownership, cross-partition edge, ordering, failure, and checkpoint semantics and
should not be treated as a routine optimization.
