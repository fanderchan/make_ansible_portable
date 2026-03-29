import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from .builder import (
    BuildError,
    build_portable_bundle,
    freeze_build_lock,
    inspect_source,
    install_bundle_extras,
)


def _add_pip_options(parser):
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable used for pip/install and runtime validation. Default: current interpreter.",
    )
    parser.add_argument(
        "--wheelhouse",
        type=Path,
        help="Optional local wheel directory. Passed to pip via --find-links.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Build without PyPI access. Requires --wheelhouse and/or local package files.",
    )


def _add_extras_options(parser):
    parser.add_argument(
        "--extra-package",
        action="append",
        default=[],
        help="Extra Python package spec installed into ansible/extras. Can be repeated.",
    )
    parser.add_argument(
        "--extra-requirements",
        action="append",
        default=[],
        type=Path,
        help="requirements.txt installed into ansible/extras. Can be repeated.",
    )
    parser.add_argument(
        "--constraint",
        type=Path,
        help="Optional pip constraints file used when installing extras.",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="make_ansible_portable",
        description="Build a self-contained portable Ansible bundle from an official package.",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    build = subparsers.add_parser(
        "build",
        help="Build a portable Ansible bundle and tarball.",
    )
    build.add_argument(
        "--source",
        required=True,
        help="Official package source. Examples: ansible-core==2.15.13, /tmp/ansible_core-2.15.13.whl, /tmp/ansible-core-2.15.13.tar.gz",
    )
    build.add_argument(
        "--bundle-name",
        help="Top-level output directory name. Default: portable-<package>-<version>.",
    )
    build.add_argument(
        "--output-dir",
        default=Path("dist"),
        type=Path,
        help="Output directory for the unpacked bundle and tarball. Default: ./dist",
    )
    build.add_argument(
        "--compression",
        choices=("bz2", "gz", "xz"),
        default="gz",
        help="Tarball compression format. Default: gz",
    )
    build.add_argument(
        "--clean-output",
        action="store_true",
        help="Delete an existing output directory/tarball with the same bundle name.",
    )
    build.add_argument(
        "--skip-archive",
        action="store_true",
        help="Create only the unpacked bundle directory and skip the tarball.",
    )
    build.add_argument(
        "--skip-self-test",
        action="store_true",
        help="Skip 'python <bundle>/ansible localhost -m ping' validation.",
    )
    build.add_argument(
        "--build-constraint",
        type=Path,
        help="Optional pip constraints file applied when installing the main Ansible/runtime dependencies.",
    )
    build.add_argument(
        "--strip-metadata",
        action="store_true",
        help="Remove *.dist-info and *.egg-info from the final bundle to reduce size. Warning: this can also remove upstream license metadata from bundled dependencies.",
    )
    _add_pip_options(build)
    _add_extras_options(build)

    extras = subparsers.add_parser(
        "install-extras",
        help="Install extra Python packages into an existing portable bundle.",
    )
    extras.add_argument(
        "--bundle",
        required=True,
        type=Path,
        help="Path to the unpacked portable bundle directory.",
    )
    extras.add_argument(
        "--self-test",
        action="store_true",
        help="Run localhost ping after installing extras.",
    )
    _add_pip_options(extras)
    _add_extras_options(extras)

    inspect_cmd = subparsers.add_parser(
        "inspect-source",
        help="Inspect an official source package and print runtime requirements.",
    )
    inspect_cmd.add_argument(
        "--source",
        required=True,
        help="Official package source. Examples: ansible-core==2.15.13 or /tmp/ansible_core-2.15.13.whl",
    )
    inspect_cmd.add_argument(
        "--json",
        action="store_true",
        help="Print full metadata as JSON.",
    )
    _add_pip_options(inspect_cmd)

    refresh = subparsers.add_parser(
        "refresh-tested-matrix",
        help="Test the last patch release of each ansible-core minor and refresh the README matrix.",
    )
    refresh.add_argument(
        "--start-minor",
        default="2.10",
        help="First minor version to include. Default: 2.10",
    )
    refresh.add_argument(
        "--end-minor",
        help="Optional last minor version to include. Default: latest stable minor on PyPI.",
    )
    refresh.add_argument(
        "--readme",
        default=Path("README.md"),
        type=Path,
        help="README file whose tested-matrix section will be rewritten. Default: ./README.md",
    )
    refresh.add_argument(
        "--output-dir",
        default=Path("dist-tests"),
        type=Path,
        help="Directory for unpacked matrix test bundles. Default: ./dist-tests",
    )
    refresh.add_argument(
        "--results-json",
        type=Path,
        help="Optional JSON output path. Default: <output-dir>/tested-matrix.json",
    )
    refresh.add_argument(
        "--python-candidate",
        action="append",
        default=[],
        help="Python executable candidate used for auto-selection. Can be repeated.",
    )
    refresh.add_argument(
        "--python-override",
        action="append",
        default=[],
        help="Force one minor to use a specific Python. Format: 2.18=/path/to/python",
    )
    refresh.add_argument(
        "--skip-readme-update",
        action="store_true",
        help="Run tests and write JSON, but do not rewrite README.",
    )
    refresh.add_argument(
        "--wheelhouse",
        type=Path,
        help="Optional local wheel directory passed to pip during each build.",
    )
    refresh.add_argument(
        "--offline",
        action="store_true",
        help="Build the tested bundles without PyPI package downloads. PyPI JSON is still queried for release metadata.",
    )

    freeze = subparsers.add_parser(
        "freeze-build-lock",
        help="Resolve and write a reproducible constraints file for the main Ansible/runtime dependencies.",
    )
    freeze.add_argument(
        "--source",
        required=True,
        help="Official package source. Examples: ansible-base==2.10.17 or ansible-core==2.15.13",
    )
    freeze.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output constraints file path.",
    )
    freeze.add_argument(
        "--build-constraint",
        type=Path,
        help="Optional existing constraints file applied during resolution.",
    )
    _add_pip_options(freeze)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "build":
            result = build_portable_bundle(args)
            print(f"Bundle directory: {result.bundle_dir}")
            if result.archive_path:
                print(f"Bundle archive:    {result.archive_path}")
            print(f"Manifest:          {result.manifest_path}")
            return 0

        if args.command == "install-extras":
            result = install_bundle_extras(args)
            print(f"Extras target:     {result.extras_dir}")
            if args.self_test:
                print("Self-test:         OK")
            print(f"Manifest:          {result.manifest_path}")
            return 0

        if args.command == "inspect-source":
            metadata = inspect_source(
                source=args.source,
                python_bin=args.python,
                wheelhouse=args.wheelhouse,
                offline=args.offline,
            )
            if args.json:
                print(json.dumps(metadata.to_dict(), indent=2, ensure_ascii=True))
            else:
                print(f"Package: {metadata.package_name}")
                print(f"Version: {metadata.version}")
                if metadata.official_controller_min_python:
                    print(f"Control-node minimum Python 3: {metadata.official_controller_min_python}")
                    if metadata.official_controller_support:
                        print(f"Official control-node support: {metadata.official_controller_support}")
                    if metadata.official_controller_support_note:
                        print(f"Official note: {metadata.official_controller_support_note}")
                    if metadata.official_controller_support_url:
                        print(f"Official docs: {metadata.official_controller_support_url}")
                elif metadata.requires_python:
                    print(f"Package metadata Requires-Python: {metadata.requires_python}")
                print(f"Artifact: {metadata.artifact_path}")
                print("Runtime requirements:")
                for requirement in metadata.runtime_requirements:
                    print(requirement)
            return 0

        if args.command == "refresh-tested-matrix":
            from .matrix import refresh_tested_matrix

            result = refresh_tested_matrix(args)
            passed = sum(1 for entry in result.entries if entry.status == "已测通过")
            print(f"README:            {result.readme_path}")
            print(f"Results JSON:      {result.results_json_path}")
            print(f"Passed minors:     {passed}/{len(result.entries)}")
            return 0 if result.all_passed else 1

        if args.command == "freeze-build-lock":
            result = freeze_build_lock(args)
            print(f"Lock file:         {result.lock_path}")
            print(f"Source package:    {result.source.package_name} {result.source.version}")
            print(f"Python:            {result.python['version'].splitlines()[0]}")
            return 0

    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
