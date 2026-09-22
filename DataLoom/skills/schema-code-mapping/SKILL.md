---
id: schema-code-mapping
version: 0.1.0
roles: [project-understanding]
allowed-tools: [read_project_file, search_project, inspect_schema]
input-contracts: [TaskSpec]
output-contracts: [EvidencePackage]
---

# Schema-Code Mapping

Map a code-level business rule to physical relations and fields only through
explicit ORM declarations, query construction, migrations, serializers, or
other repository evidence. Preserve table and field names exactly. When the
mapping depends on uninspected configuration or runtime substitution, record
that dependency as unresolved.

