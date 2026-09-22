---
name: business-rule-tracing
description: Trace task-critical business decisions from public terms through repository call paths to production implementations, producing source-backed EvidencePackage rules.
allowed-tools: [read_project_file, search_project]
metadata:
  id: business-rule-tracing
  version: 0.2.0
  roles: [project-understanding]
  input-contracts: [TaskSpec]
  output-contracts: [EvidencePackage]
---

# Business Rule Tracing

Start from the business terms in the public task and identify each decision
whose implementation can change the result. Search for those terms, then trace
callers and callees until reaching the production predicate, transformation,
scope, state transition, or policy that makes the decision.

UI code, documentation, and tests are discovery leads or behavioral examples;
they do not by themselves establish a core production rule. For every core
rule, cite at least one production source range that directly participates in
the decision. Record the route used to reach it through the selected source
references and symbols. Stop tracing once the complete deciding expression and
its inputs are established.

Describe the rule's inputs by their roles (`SUBJECT`, `EXISTING_STATE`,
`CONFIGURATION`, or `CONTEXT`), its predicate, and its boundary behavior. Do
not collapse multiple participating entities into a generic statement. Mark a
claim `UNRESOLVED` when the production decision cannot be located; never fill a
missing rule from tests, UI labels, common expectations, prior runs, or
evaluation feedback. An unresolved core rule makes the package incomplete.
