---
name: boundary-and-exception-analysis
description: Extract production-defined boundaries, exclusions, defaults, and early returns for task-critical business rules.
allowed-tools: [read_project_file, search_project]
metadata:
  id: boundary-and-exception-analysis
  version: 0.2.0
  roles: [project-understanding]
  input-contracts: [TaskSpec]
  output-contracts: [EvidencePackage]
---

# Boundary and Exception Analysis

For each candidate rule, inspect whether code defines time boundaries, null
semantics, soft deletion, state exclusions, ordering, default scope, or early
returns. Add each confirmed exception to the same rule and cite its source.
Express equality and adjacency behavior explicitly when comparisons or ranges
affect the outcome. Check boundaries for every participating input entity, not
only the task's primary subject. Do not infer an exception merely because it is
common in similar projects or appears in a test without a traced production
implementation. If production behavior remains ambiguous, keep the core rule
unresolved and the EvidencePackage incomplete.
