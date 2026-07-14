# Fixed-snapshot controller benchmark

The controller benchmark reloads the same checksummed world snapshot for every case. A
case supplies a controller component and an async character-agent implementation, so the
same harness covers scripted controllers, behavior trees, goal-directed agents, model
providers, and future learned-policy adapters registered through the uniform controller
contract.

Each turn uses the normal prompt, tool schema, dispatch, command queue, mutation executor,
and `CommitReceipt` path. Results report structural validity, committed and rejected
commands, recovery within two later decisions, elapsed time, and whether each decision
record contains its input epoch, governing-pressure category, candidates, selected action,
command ID, and terminal result. The snapshot checksum and saved seed are included in every
case result so comparisons cannot silently use different starting worlds.

Callers may also supply named outcome probes. Each probe reads the authoritative world only
after the case finishes, and its boolean result is recorded with the controller metrics.
Story benchmarks use these probes for durable consequences such as item custody, incident
resolution, fulfilled obligations, written reports, and relationship changes; a committed
tool call alone is not treated as story success.

Live model cases should pin provider, model, prompt template, snapshot, and seed in the
calling test or release job. The harness does not grant controllers direct ECS access and
does not treat a tool call as success until the authoritative actor records its receipt.
