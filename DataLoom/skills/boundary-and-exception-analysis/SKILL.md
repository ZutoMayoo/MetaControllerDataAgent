---
id: boundary-and-exception-analysis
version: 0.1.0
roles: [project-understanding]
allowed-tools: [read_project_file, search_project]
input-contracts: [TaskSpec]
output-contracts: [EvidencePackage]
---

# Boundary and Exception Analysis

For each candidate rule, inspect whether code defines time boundaries, null
semantics, soft deletion, state exclusions, ordering, default scope, or early
returns. Add each confirmed exception to the same rule and cite its source.
Do not infer an exception merely because it is common in similar projects.

