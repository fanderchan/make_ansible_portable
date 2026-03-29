from __future__ import annotations

import configparser
import email
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import TOOL_NAME, TOOL_VERSION

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = PROJECT_ROOT / "templates"
MANIFEST_FILE = "portable-manifest.json"
PROJECT_LICENSE = PROJECT_ROOT / "LICENSE"
PROJECT_NOTICE = PROJECT_ROOT / "NOTICE"
PROJECT_ACKNOWLEDGEMENTS = PROJECT_ROOT / "ACKNOWLEDGEMENTS.md"
FALLBACK_COMMANDS = [
    "ansible",
    "ansible-config",
    "ansible-connection",
    "ansible-console",
    "ansible-doc",
    "ansible-galaxy",
    "ansible-inventory",
    "ansible-playbook",
    "ansible-pull",
    "ansible-vault",
]


class BuildError(RuntimeError):
    pass


@dataclass
class SourceMetadata:
    input_source: str
    artifact_path: Path
    package_name: str
    version: str
    runtime_requirements: list[str]

    def to_dict(self) -> dict[str, object]:
        source_path = Path(self.input_source).expanduser()
        return {
            "input_source": self.input_source,
            "artifact_name": self.artifact_path.name,
            "artifact_path": str(source_path.resolve()) if source_path.exists() else None,
            "package_name": self.package_name,
            "version": self.version,
            "runtime_requirements": self.runtime_requirements,
        }


@dataclass
class BuildResult:
    bundle_dir: Path
    archive_path: Path | None
    manifest_path: Path


@dataclass
class ExtrasInstallResult:
    extras_dir: Path
    manifest_path: Path


def _run(cmd: list[str], *, cwd: Path | None = None) -> None:
    try:
        subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"Command failed ({exc.returncode}): {' '.join(cmd)}") from exc


def _sanitize_name(value: str) -> str:
    chars = []
    for ch in value.lower():
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("-")
    result = "".join(chars)
    while "--" in result:
        result = result.replace("--", "-")
    return result.strip("-")


def _download_artifact(
    source: str,
    *,
    python_bin: str,
    download_dir: Path,
    wheelhouse: Path | None,
    offline: bool,
) -> Path:
    download_dir.mkdir(parents=True, exist_ok=True)
    before = {item.name for item in download_dir.iterdir()}
    cmd = [python_bin, "-m", "pip", "download", "--no-deps", "--dest", str(download_dir)]
    if wheelhouse:
        cmd.extend(["--find-links", str(wheelhouse)])
    if offline:
        cmd.append("--no-index")
    cmd.append(source)
    _run(cmd)
    after = sorted(item for item in download_dir.iterdir() if item.is_file() and item.name not in before)
    if not after:
        raise BuildError(f"No artifact downloaded for source: {source}")
    if len(after) > 1:
        return after[-1]
    return after[0]


def _read_member_from_tar(artifact: Path, member_suffix: str) -> str | None:
    with tarfile.open(artifact, "r:*") as archive:
        for member in archive.getmembers():
            if member.name.endswith(member_suffix) and member.isfile():
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                return extracted.read().decode("utf-8", "replace")
    return None


def _read_member_from_zip(artifact: Path, member_suffix: str) -> str | None:
    with zipfile.ZipFile(artifact) as archive:
        for member in archive.namelist():
            if member.endswith(member_suffix):
                return archive.read(member).decode("utf-8", "replace")
    return None


def _parse_email_metadata(raw_text: str) -> email.message.Message:
    return email.message_from_string(raw_text)


def _parse_requirements_text(raw_text: str) -> list[str]:
    requirements: list[str] = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirements.append(line)
    return requirements


def _inspect_wheel(artifact: Path, input_source: str) -> SourceMetadata:
    with zipfile.ZipFile(artifact) as archive:
        metadata_name = next(
            (name for name in archive.namelist() if name.endswith(".dist-info/METADATA")),
            None,
        )
        if metadata_name is None:
            raise BuildError(f"Could not find METADATA in wheel: {artifact}")
        message = _parse_email_metadata(archive.read(metadata_name).decode("utf-8", "replace"))
    return SourceMetadata(
        input_source=input_source,
        artifact_path=artifact,
        package_name=message["Name"],
        version=message["Version"],
        runtime_requirements=message.get_all("Requires-Dist", []),
    )


def _inspect_sdist(artifact: Path, input_source: str) -> SourceMetadata:
    if zipfile.is_zipfile(artifact):
        pkg_info = _read_member_from_zip(artifact, "/PKG-INFO")
        requirements_txt = _read_member_from_zip(artifact, "/requirements.txt")
    else:
        pkg_info = _read_member_from_tar(artifact, "/PKG-INFO")
        requirements_txt = _read_member_from_tar(artifact, "/requirements.txt")

    if not pkg_info:
        raise BuildError(f"Could not find PKG-INFO in source archive: {artifact}")

    message = _parse_email_metadata(pkg_info)
    runtime_requirements = message.get_all("Requires-Dist", [])
    if not runtime_requirements and requirements_txt:
        runtime_requirements = _parse_requirements_text(requirements_txt)

    return SourceMetadata(
        input_source=input_source,
        artifact_path=artifact,
        package_name=message["Name"],
        version=message["Version"],
        runtime_requirements=runtime_requirements,
    )


def _inspect_artifact(artifact: Path, input_source: str) -> SourceMetadata:
    if artifact.suffix == ".whl":
        return _inspect_wheel(artifact, input_source)
    if artifact.suffix in {".zip", ".gz", ".bz2", ".xz"} or artifact.name.endswith(".tar.gz") or artifact.name.endswith(".tar.bz2") or artifact.name.endswith(".tar.xz"):
        return _inspect_sdist(artifact, input_source)
    raise BuildError(f"Unsupported artifact type: {artifact}")


def inspect_source(
    *,
    source: str,
    python_bin: str,
    wheelhouse: Path | None,
    offline: bool,
) -> SourceMetadata:
    return _resolve_source_metadata(
        source=source,
        python_bin=python_bin,
        wheelhouse=wheelhouse,
        offline=offline,
        download_dir=None,
    )


def _resolve_source_metadata(
    *,
    source: str,
    python_bin: str,
    wheelhouse: Path | None,
    offline: bool,
    download_dir: Path | None,
) -> SourceMetadata:
    source_path = Path(source).expanduser()
    if source_path.exists():
        artifact = source_path.resolve()
    else:
        if download_dir is None:
            with tempfile.TemporaryDirectory(prefix="portable-source-") as temp_dir:
                artifact = _download_artifact(
                    source,
                    python_bin=python_bin,
                    download_dir=Path(temp_dir),
                    wheelhouse=wheelhouse,
                    offline=offline,
                )
                return _inspect_artifact(artifact, source)
        artifact = _download_artifact(
            source,
            python_bin=python_bin,
            download_dir=download_dir,
            wheelhouse=wheelhouse,
            offline=offline,
        )

    return _inspect_artifact(artifact, source)


def _install_with_pip(
    *,
    python_bin: str,
    target: Path,
    packages: list[str] | None = None,
    requirement_files: list[Path] | None = None,
    constraint_file: Path | None = None,
    wheelhouse: Path | None = None,
    offline: bool,
) -> None:
    packages = packages or []
    requirement_files = requirement_files or []
    if not packages and not requirement_files:
        return

    cmd = [python_bin, "-m", "pip", "install", "--upgrade", "--no-compile", "--target", str(target)]
    if wheelhouse:
        cmd.extend(["--find-links", str(wheelhouse)])
    if offline:
        cmd.append("--no-index")
    if constraint_file:
        cmd.extend(["--constraint", str(constraint_file)])
    for requirement_file in requirement_files:
        cmd.extend(["--requirement", str(requirement_file)])
    cmd.extend(packages)
    _run(cmd)


def _discover_ansible_commands(ansible_dir: Path) -> list[str]:
    entry_points = sorted(ansible_dir.glob("*.dist-info/entry_points.txt"))
    if not entry_points:
        entry_points = sorted(ansible_dir.glob("*.egg-info/entry_points.txt"))
    if not entry_points:
        return FALLBACK_COMMANDS

    parser = configparser.ConfigParser()
    parser.read(entry_points[0], encoding="utf-8")
    if not parser.has_section("console_scripts"):
        return FALLBACK_COMMANDS
    commands = sorted(name for name in parser["console_scripts"] if name.startswith("ansible"))
    return commands or FALLBACK_COMMANDS


def _write_quickstart(bundle_dir: Path, commands: list[str], metadata: SourceMetadata) -> None:
    quickstart = bundle_dir / "QUICKSTART.txt"
    lines = [
        "Portable Ansible Quickstart",
        "===========================",
        "",
        f"Source package: {metadata.package_name} {metadata.version}",
        "",
        "Run examples:",
        "  python3 ./ansible localhost -m ping",
        "  python3 ./ansible-playbook playbook.yml",
        "",
        "Installed command aliases:",
    ]
    lines.extend(f"  {command}" for command in commands)
    lines.extend(
        [
            "",
            "Third-party Python dependencies can be installed into ./ansible/extras.",
            "Manual example:",
            "  python3 -m pip install -t ./ansible/extras PyMySQL",
            "",
            "Project helper example (run from make_ansible_portable project root):",
            "  ./install-extras.sh --bundle /path/to/unpacked-bundle --extra-requirements requirements.txt",
        ]
    )
    quickstart.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_bundle_notices(bundle_dir: Path, metadata: SourceMetadata) -> None:
    if PROJECT_LICENSE.exists():
        shutil.copy2(PROJECT_LICENSE, bundle_dir / "LICENSE")
    if PROJECT_NOTICE.exists():
        shutil.copy2(PROJECT_NOTICE, bundle_dir / "NOTICE")
    if PROJECT_ACKNOWLEDGEMENTS.exists():
        shutil.copy2(PROJECT_ACKNOWLEDGEMENTS, bundle_dir / "ACKNOWLEDGEMENTS.md")

    notices = bundle_dir / "UPSTREAM-NOTICES.txt"
    lines = [
        "Portable Ansible Bundle Notices",
        "===============================",
        "",
        f"Source package: {metadata.package_name} {metadata.version}",
        "",
        "This bundle contains upstream Ansible packages and Python dependencies",
        "under their own licenses.",
        "",
        "Repository launcher code and related project files in this bundle are",
        "distributed under Apache License 2.0. See LICENSE, NOTICE and",
        "ACKNOWLEDGEMENTS.md in the bundle root.",
        "",
        "Upstream package metadata and license files are normally kept under",
        "./ansible/*.dist-info.",
        "",
        "If you build with --strip-metadata, review redistribution obligations",
        "before sharing the resulting bundle.",
    ]
    notices.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _create_command_symlinks(bundle_dir: Path, commands: list[str]) -> None:
    for command in commands:
        if command == "ansible":
            continue
        link = bundle_dir / command
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink("ansible", link)


def _remove_matching(root: Path, pattern: str) -> None:
    for path in root.rglob(pattern):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()


def _prune_bundle(ansible_dir: Path, *, strip_metadata: bool) -> None:
    _remove_matching(ansible_dir, "__pycache__")
    for file_path in ansible_dir.rglob("*.pyc"):
        file_path.unlink()

    ansible_test_dir = ansible_dir / "ansible_test"
    if ansible_test_dir.exists():
        shutil.rmtree(ansible_test_dir)

    core_bin_dir = ansible_dir / "bin"
    if core_bin_dir.exists():
        shutil.rmtree(core_bin_dir)

    if strip_metadata:
        for pattern in ("*.dist-info", "*.egg-info"):
            _remove_matching(ansible_dir, pattern)


def _write_manifest(
    *,
    bundle_dir: Path,
    metadata: SourceMetadata,
    commands: list[str],
    python_bin: str,
    build_extras: dict[str, object],
) -> Path:
    manifest_path = bundle_dir / MANIFEST_FILE
    manifest = {
        "builder": {
            "name": TOOL_NAME,
            "version": TOOL_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(),
        },
        "source": metadata.to_dict(),
        "python": {
            "executable": python_bin,
            "version": sys.version,
        },
        "bundle": {
            "name": bundle_dir.name,
            "commands": commands,
            "ansible_dir": "ansible",
            "extras_dir": "ansible/extras",
        },
        "build_extras": build_extras,
        "extra_installs": [],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return manifest_path


def _load_manifest(manifest_path: Path) -> dict[str, object]:
    if not manifest_path.exists():
        raise BuildError(f"Missing manifest file: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _save_manifest(manifest_path: Path, manifest: dict[str, object]) -> None:
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _compile_launcher(python_bin: str, ansible_dir: Path) -> None:
    py_compile.compile(str(ansible_dir / "__main__.py"), doraise=True)


def _self_test_bundle(python_bin: str, bundle_dir: Path) -> None:
    _run([python_bin, str(bundle_dir / "ansible"), "localhost", "-m", "ping"])


def _create_archive(bundle_dir: Path, compression: str) -> Path:
    suffix = {
        "bz2": ".tar.bz2",
        "gz": ".tar.gz",
        "xz": ".tar.xz",
    }[compression]
    mode = {
        "bz2": "w:bz2",
        "gz": "w:gz",
        "xz": "w:xz",
    }[compression]
    archive_path = bundle_dir.parent / f"{bundle_dir.name}{suffix}"
    with tarfile.open(archive_path, mode) as archive:
        archive.add(bundle_dir, arcname=bundle_dir.name)
    return archive_path


def build_portable_bundle(args) -> BuildResult:
    with tempfile.TemporaryDirectory(prefix="portable-build-") as temp_dir:
        temp_root = Path(temp_dir)
        metadata = _resolve_source_metadata(
            source=args.source,
            python_bin=args.python,
            wheelhouse=args.wheelhouse,
            offline=args.offline,
            download_dir=temp_root / "downloads",
        )
        bundle_name = args.bundle_name or f"portable-{_sanitize_name(metadata.package_name)}-{metadata.version}"
        output_dir = args.output_dir.resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir = output_dir / bundle_name
        archive_candidates = [
            output_dir / f"{bundle_name}.tar.bz2",
            output_dir / f"{bundle_name}.tar.gz",
            output_dir / f"{bundle_name}.tar.xz",
        ]
        archive_suffix = {
            "bz2": ".tar.bz2",
            "gz": ".tar.gz",
            "xz": ".tar.xz",
        }[args.compression]
        archive_path = output_dir / f"{bundle_name}{archive_suffix}"

        if bundle_dir.exists():
            if not args.clean_output:
                raise BuildError(f"Output bundle already exists: {bundle_dir}. Use --clean-output to overwrite.")
            shutil.rmtree(bundle_dir)
        if args.clean_output:
            for candidate in archive_candidates:
                if candidate.exists():
                    candidate.unlink()

        stage_root = temp_root / bundle_name
        ansible_dir = stage_root / "ansible"
        extras_dir = ansible_dir / "extras"
        stage_root.mkdir(parents=True)
        ansible_dir.mkdir()
        extras_dir.mkdir()

        launcher_src = TEMPLATES_DIR / "__main__.py"
        if not launcher_src.exists():
            raise BuildError(f"Missing launcher template: {launcher_src}")
        shutil.copy2(launcher_src, ansible_dir / "__main__.py")

        _install_with_pip(
            python_bin=args.python,
            target=ansible_dir,
            packages=[str(metadata.artifact_path)],
            wheelhouse=args.wheelhouse,
            offline=args.offline,
        )
        _compile_launcher(args.python, ansible_dir)

        if args.extra_package or args.extra_requirements:
            _install_with_pip(
                python_bin=args.python,
                target=extras_dir,
                packages=args.extra_package,
                requirement_files=args.extra_requirements,
                constraint_file=args.constraint,
                wheelhouse=args.wheelhouse,
                offline=args.offline,
            )

        commands = _discover_ansible_commands(ansible_dir)
        _create_command_symlinks(stage_root, commands)
        _write_quickstart(stage_root, commands, metadata)
        _write_bundle_notices(stage_root, metadata)
        manifest_path = _write_manifest(
            bundle_dir=stage_root,
            metadata=metadata,
            commands=commands,
            python_bin=args.python,
            build_extras={
                "packages": args.extra_package,
                "requirement_files": [str(path) for path in args.extra_requirements],
                "constraint_file": str(args.constraint) if args.constraint else None,
            },
        )
        _prune_bundle(ansible_dir, strip_metadata=args.strip_metadata)
        shutil.move(str(stage_root), str(bundle_dir))

    if not args.skip_self_test:
        _self_test_bundle(args.python, bundle_dir)

    created_archive = None if args.skip_archive else _create_archive(bundle_dir, args.compression)
    return BuildResult(
        bundle_dir=bundle_dir,
        archive_path=created_archive,
        manifest_path=bundle_dir / MANIFEST_FILE,
    )


def _bundle_paths(bundle_dir: Path) -> tuple[Path, Path, Path]:
    bundle_root = bundle_dir.resolve()
    ansible_dir = bundle_root / "ansible"
    extras_dir = ansible_dir / "extras"
    manifest_path = bundle_root / MANIFEST_FILE
    if not ansible_dir.is_dir():
        raise BuildError(f"Invalid bundle. Missing directory: {ansible_dir}")
    extras_dir.mkdir(parents=True, exist_ok=True)
    return ansible_dir, extras_dir, manifest_path


def install_bundle_extras(args) -> ExtrasInstallResult:
    bundle_dir = args.bundle.resolve()
    _, extras_dir, manifest_path = _bundle_paths(bundle_dir)

    if not args.extra_package and not args.extra_requirements:
        raise BuildError("Nothing to install. Provide --extra-package and/or --extra-requirements.")

    _install_with_pip(
        python_bin=args.python,
        target=extras_dir,
        packages=args.extra_package,
        requirement_files=args.extra_requirements,
        constraint_file=args.constraint,
        wheelhouse=args.wheelhouse,
        offline=args.offline,
    )

    manifest = _load_manifest(manifest_path)
    installs = manifest.setdefault("extra_installs", [])
    installs.append(
        {
            "installed_at": datetime.now(timezone.utc).isoformat(),
            "packages": args.extra_package,
            "requirement_files": [str(path) for path in args.extra_requirements],
            "constraint_file": str(args.constraint) if args.constraint else None,
        }
    )
    _save_manifest(manifest_path, manifest)

    if args.self_test:
        _self_test_bundle(args.python, bundle_dir)

    return ExtrasInstallResult(extras_dir=extras_dir, manifest_path=manifest_path)
