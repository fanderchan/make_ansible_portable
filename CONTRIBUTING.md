# Contributing

## Scope

- Keep this repository focused on building portable bundles from official
  `ansible-base` and `ansible-core` packages.
- Prefer minimal, well-documented runtime glue over deep changes to Ansible
  behavior.

## Before Opening A Change

- Prefer changes that preserve reproducibility.
- If you update supported Ansible minors, run
  `./refresh-tested-matrix.sh --start-minor 2.10 ...` with matching Python
  interpreters and refresh the README matrix.
- If you add optional extras examples, make sure they install cleanly into
  `ansible/extras`.
- If you touch licensing or attribution text, keep `LICENSE`, `NOTICE`,
  `README.md`, and `ACKNOWLEDGEMENTS.md` consistent.

## Pull Request Checklist

- Update documentation when CLI flags, defaults, or output layout changes.
- Keep generated artifacts out of commits. `dist/` and bundle directories under
  `dist-tests/` should remain untracked.
- Keep the launcher implementation self-contained and repository-owned; avoid
  copying upstream source text into this repository.

## Contribution License

- By contributing to this repository, you agree that your changes are provided
  under the repository license, Apache License 2.0.
