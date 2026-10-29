# Standalone migration

Canonical repository: https://github.com/splitintech/neighborhood-map-studio

Extracted from `87b71450ce3422ec80112de4c680f77775de6937` in splitintech/open-internal-tools. The product directory is now the repository root. Relevant history, authors, modes, assets, tests, documentation and release tooling are preserved. The [commit map](migration/commit-map.txt) maps upstream IDs to filtered history; signed upstream tags remain in the hub and are not recreated.

Map Studio also incorporates all 80 service files from SplitIn `08713aed305fc720ce8286dd114475d9034bb69c`, including the later readiness and operator fixes. Both histories are reachable through a merge. See [SplitIn commit map](migration/splitin-commit-map.txt) and [source inventory](migration/splitin-source-files.json). No original hub files were lost. The existing SplitIn consumer copy is retained; changing that application is a separate integration rollout.

[Original hub inventory](migration/hub-source-files.json), [selected source inventory](migration/source-files.json), [migration snapshot](migration/snapshot.json), and [validation](migration/validation.json) provide file-level provenance and explain intentional changes. Run `python3 scripts/check-migration.py --snapshot` to verify the exact migration.

Migration creates a source repository, not an npm release, live deployment, provider qualification, database rollout or credential transfer. Roll back consumers to their previous artifact or use the immutable upstream revision. The original feature branches are retained as historical sources.
