---
name: schema-code-mapping
description: Map production-backed business semantics to physical database relations and fields without inventing schema relationships.
allowed-tools: [read_project_file, search_project, inspect_schema]
metadata:
  id: schema-code-mapping
  version: 0.2.0
  roles: [project-understanding]
  input-contracts: [TaskSpec]
  output-contracts: [EvidencePackage]
---

# Schema-Code Mapping

Map a code-level business rule to physical relations and fields only through
explicit ORM declarations, query construction, migrations, serializers, or
other repository evidence. Preserve table and field names exactly, and bind
each mapped field to the corresponding semantic input role. Keep fields owned
by different entities separate even when their names or types are similar.

A schema declaration proves storage shape, not decision behavior. Mark schema
references as `SCHEMA_MAPPING`; do not use them as
`DECISION_IMPLEMENTATION` unless the cited production expression actually
makes the decision. When a mapping depends on uninspected configuration,
runtime substitution, an external service, or a database object absent from
the repository, record that dependency as unresolved.
