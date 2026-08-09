# Operational journal VPS before/after comparison

Measured on 2026-08-09 on the Bunnyland VPS (`vps-5fbee3ca`, Linux
`7.0.0-27-generic`, Python 3.14.4). The deployed server was healthy at commit `2b21d93`
during the run. The benchmark used isolated directories under `/tmp`; it did not read or
modify the live journal, restart containers, or deploy this change.

## Result

The fixture contained 5,000 JSONL records totaling 37,883,890 bytes (36.129 MiB), with a
7,577-byte new record. Fifty before/after append trials were interleaved to reduce ordering
bias. Every write retained the production durability operations: record `flush` plus
`fsync`, atomic rename where applicable, and directory `fsync`.

| Path | Median | Mean (95% CI) | p95 | Range |
| --- | ---: | ---: | ---: | ---: |
| Before: append, reread, bound, and rewrite monolith | 103.795 ms | 107.964 ms (105.641–110.286) | 119.053 ms | 100.514–142.578 ms |
| After: delete oldest segment and append one record | 0.191 ms | 0.200 ms (0.187–0.214) | 0.220 ms | 0.177–0.516 ms |
| One-time migration (10 trials) | 71.637 ms | 71.832 ms (70.935–72.729) | 73.342 ms | 70.392–74.275 ms |

The median append was **544.08× faster** (99.816% lower latency). The old path was slower
in all 50 paired trials; an exact two-sided paired sign test gives
`p = 1.7763568394002505e-15`. This is strong evidence for this VPS and fixture, although it
is not a claim about every filesystem or workload.

Per bounded append, the old algorithm read 37,891,467 bytes and rewrote 37,883,890 bytes.
The segmented algorithm read no completed-segment bytes and wrote only the 7,577-byte new
record. The measured after case is the retention boundary, which includes deleting the
oldest segment and `fsync`ing the directory; ordinary non-rotation appends do less work.

## Real trace evidence

The phase traces below are direct `perf_counter` observations from the same VPS. These two
representative runs were additionally wrapped in `strace`, so their totals include tracing
overhead and are evidence of path shape rather than inputs to the latency table.

Before trace:

```json
{
  "append_and_record_fsync_ms": 0.5185361951589584,
  "read_and_bound_ms": 85.70629125460982,
  "rewrite_and_file_fsync_ms": 37.572506349533796,
  "replace_and_directory_fsync_ms": 3.662623930722475,
  "total_ms": 127.4783331900835
}
```

```text
% time     seconds  usecs/call  calls  syscall
 58.96    0.028337       14168      2  read
 33.86    0.016275          54    296  write
  7.09    0.003407        3407      1  rename
  0.06    0.000030           7      4  openat
  0.02    0.000012           4      3  fsync
100.00    0.048061         157    306  total
```

After trace at the retention boundary:

```json
{
  "delete_and_directory_fsync_ms": 0.4525650292634964,
  "append_and_record_fsync_ms": 0.37812208756804466,
  "total_ms": 0.8356240577995777
}
```

```text
% time     seconds  usecs/call  calls  syscall
 61.02    0.000036          36      1  unlink
 23.73    0.000014           7      2  openat
 10.17    0.000006           6      1  write
  5.08    0.000003           1      2  fsync
100.00    0.000059           9      6  total
```

The filtered syscall trace contains no `read` of a completed segment and no rewrite or
rename of one. The one-time migration traces separately measured streaming the legacy file
once, writing and `fsync`ing 50 segment temporaries, publishing them atomically, and
`fsync`ing the directory.

## Interpretation and limits

The test compares the old and new journal I/O algorithms on the real VPS storage stack,
not end-to-end tick or checkpoint time. Fixture construction was outside each timed region.
The synthetic records intentionally match the reported 36 MiB production journal size;
their payload content is not copied from production. OS cache state, neighboring VPS load,
record size, and filesystem behavior can change absolute latency. The paired interleaving,
confidence intervals, phase traces, and filtered syscall traces make the large directional
result robust without touching production data.
