---
name: iris-persistence-scaffold
description: Generate and review typed iris-persistence Python models from compiled InterSystems IRIS classes. Use for reverse scaffolding an existing IRIS namespace, choosing class patterns and related-class expansion, extracting metadata or advanced storage, resolving generated-name collisions, validating generated models, and planning a safe observe-to-managed ownership transition.
---

# Scaffold existing IRIS classes

## Workflow

1. Confirm access to a live IRIS runtime; scaffolding reads compiled dictionary metadata and cannot run from `.cls` exports alone.
2. Configure embedded or native runtime access.
3. Start with the narrowest class pattern and a new output directory.
4. Generate with `mode="observe"`, `storage="ignore"`, and `return_result=True`.
5. Review every returned warning and generated file before importing it into application code.
6. Enable `include_related=True` only when referenced class models are required.
7. Enable `extract_meta=True` only when class metadata must round-trip.
8. Use storage extraction only for expert workflows; inspect its explicit `iris_persistence.advanced_storage` imports.
9. Import the generated modules and perform read tests against representative rows.
10. Keep generated models in observe mode unless the user explicitly approves Python ownership and a reviewed migration.

Read [references/scaffold-options.md](references/scaffold-options.md) for runtime examples, option semantics, and validation checks.

## Guardrails

- Never silently convert generated models to `managed` mode.
- Never overwrite a hand-maintained model directory without comparing the generated output.
- Do not use `best_effort=True` by default. If used, surface every warning and unsupported mapping.
- Do not promise offline `.cls` scaffolding; it is not implemented.
- Treat extracted custom storage as expert configuration, not ordinary model boilerplate.

## Verification

Compile or import each generated module, then query known IDs through the observe model. In this repository, run:

```bash
pytest tests/test_scaffold.py -q
pytest tests/test_full_circle.py -q
```
