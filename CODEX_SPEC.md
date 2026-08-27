# ConsensusSeam v0.1 implementation boundaries

DO NOT:

- implement ModelFuzz;
- implement a fuzzer;
- implement TLA+ integration;
- design a universal consensus message schema;
- create a universal cross-language Adapter runtime;
- implement Java/C/Rust backends in v0.1;
- implement real network scheduling;
- implement full wall-clock virtualization;
- invent crash/restart semantics;
- split storage operations into artificial steps;
- implement agent-to-agent free-form conversations;
- add vector databases or retrieval infrastructure;
- expand the architecture unless required by a failing acceptance test.

ConsensusSeam exposes test-control seams. It does not decide which message to
deliver, when to crash, how far to advance time, or how to generate tests.
