---
id: business-rule-tracing
version: 0.1.0
roles: [project-understanding]
allowed-tools: [read_project_file, search_project]
input-contracts: [TaskSpec]
output-contracts: [EvidencePackage]
---

# Business Rule Tracing

Start from the business terms in the task. Locate the deciding predicate, status
transition, enum set, scope, or service method in the frozen repository. Follow
only calls required to establish the rule. Record the condition, exclusions,
and source locations. Mark a claim `UNRESOLVED` when its source cannot be
located; never fill a missing rule from common business expectations.

