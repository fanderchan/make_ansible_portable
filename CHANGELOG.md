# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic
Versioning.

## [0.3.0] - 2026-03-30

### Added

- Support for installing Ansible collections into the portable bundle at build
  time via `--extra-collection` and `--extra-collection-requirements`.
- `install-collections.sh` for adding collections to an existing unpacked
  bundle after the initial build.
- Automatic collection-path activation in the portable launcher so bundled
  collections under `./collections` are visible to `ansible-playbook`,
  `ansible-doc`, and `ansible-galaxy`.
- Collection install tracking in `portable-manifest.json`.

### Changed

- Documented that collection compatibility must be checked explicitly against
  the target Ansible version and deployment scenario instead of assuming the
  latest collection release will fit older control-node or managed-node setups.
- Updated the collection example to pin `ansible.posix:==1.5.4` for
  conservative compatibility with `ansible-base 2.10.x` workflows.

## [0.2.0] - 2026-03-30

### Added

- Auto-bootstrap of an isolated build toolchain for the selected target Python,
  including Python 3.6-compatible `pip` / `setuptools` / `wheel` pinning.
- Official control-node Python support mapping used by `build` and
  `inspect-source` before falling back to package metadata.
- Automatic matching of checked-in build-constraint lock files for supported
  source-package and Python combinations.
- Bundle size reduction flags for dropping `ansible-vault` runtime support and
  the optional PyYAML C extension.

### Changed

- Improved default lock workflow, CLI help text, and user documentation for
  reproducible builds and tested-version matrix refreshes.

### Fixed

- Python 3.6 compatibility for build commands and dependency resolution on
  legacy control nodes.

## [0.1.0] - 2026-03-29

### Added

- Initial public release of `make_ansible_portable`.
- One-command portable bundle builder for official `ansible-base` and
  `ansible-core` packages.
- Support for building from PyPI specs, local wheels, and local sdists.
- Portable launcher template that runs bundled Ansible commands from the unpacked
  directory layout.
- Extras installation flow for injecting third-party Python packages into
  `ansible/extras`.
- Source inspection command for reading official package metadata and runtime
  requirements.
- Tested-version matrix refresh command and generated README matrix for the last
  patch release of each supported Ansible Core minor from `2.10` onward.
- Repository notices and bundle notices for upstream license retention.
- GitHub Actions CI for basic validation on supported Python runtimes.
- `SECURITY.md` with vulnerability reporting guidance.
