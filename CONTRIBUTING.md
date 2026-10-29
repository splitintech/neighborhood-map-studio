# Contributing

Develop neighborhood-map-studio in this standalone repository. See [README](README.md) for setup and validation. Preserve existing package names, exports, data formats and migrations. Include focused tests for behavior changes. Keep credentials and private data outside Git. Open issues and pull requests at https://github.com/splitintech/neighborhood-map-studio.

Run `python3 scripts/check-migration.py` to verify provenance and preserved assets. `--snapshot` checks the exact initial migration; later changes must not rewrite this historical snapshot. See [migration](docs/migration.md).
