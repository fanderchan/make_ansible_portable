# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project follows Semantic
Versioning.

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

