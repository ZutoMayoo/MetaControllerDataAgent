# Third-party reusable components

DataLoom invokes these components through subprocess adapters. Their source is
kept outside the P12 repository and is not vendored here.

| Component | Reused interface | Pinned revision | License |
| --- | --- | --- | --- |
| SignalPilot | `dbt-workflow/scan_project.py`, `validate_project.py`, `SKILL.md` | `71dc57e4d915ebc2475d4cd27c6d5f8c405e5cf3` | Apache-2.0 |
| DataAgent | `dataagent.core.suite.builtin_suites.bird_benchmark.run_bird` | `8208e7cbbc0c3351c76a4c292737ca05ab92cb4f` | Apache-2.0 |

Every adapter probe records the actual Git revision and SHA-256 of the invoked
component files. Production runs should set the expected revision so a changed
external checkout fails closed. DataLoom's host-only evaluator and Gold
isolation rules remain authoritative; neither external adapter may expose Gold
to an inference role.
