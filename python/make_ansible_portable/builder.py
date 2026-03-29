import configparser
import email
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import TOOL_NAME, TOOL_VERSION
from .controller_support import lookup_controller_support

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


class SourceMetadata(object):
    def __init__(
        self,
        input_source,
        artifact_path,
        package_name,
        version,
        requires_python,
        runtime_requirements,
        official_controller_min_python="",
        official_controller_support="",
        official_controller_support_url="",
        official_controller_support_note="",
        official_controller_support_note_url="",
    ):
        self.input_source = input_source
        self.artifact_path = artifact_path
        self.package_name = package_name
        self.version = version
        self.requires_python = requires_python
        self.runtime_requirements = runtime_requirements
        self.official_controller_min_python = official_controller_min_python
        self.official_controller_support = official_controller_support
        self.official_controller_support_url = official_controller_support_url
        self.official_controller_support_note = official_controller_support_note
        self.official_controller_support_note_url = official_controller_support_note_url

    def to_dict(self):
        source_path = Path(self.input_source).expanduser()
        return {
            "input_source": self.input_source,
            "artifact_name": self.artifact_path.name,
            "artifact_path": str(source_path.resolve()) if source_path.exists() else None,
            "package_name": self.package_name,
            "version": self.version,
            "requires_python": self.requires_python,
            "runtime_requirements": self.runtime_requirements,
            "official_controller_python": {
                "minimum_python3": self.official_controller_min_python or None,
                "display": self.official_controller_support or None,
                "source_url": self.official_controller_support_url or None,
                "note": self.official_controller_support_note or None,
                "note_source_url": self.official_controller_support_note_url or None,
            },
        }


class BuildResult(object):
    def __init__(self, bundle_dir, archive_path, manifest_path):
        self.bundle_dir = bundle_dir
        self.archive_path = archive_path
        self.manifest_path = manifest_path


class ExtrasInstallResult(object):
    def __init__(self, extras_dir, manifest_path):
        self.extras_dir = extras_dir
        self.manifest_path = manifest_path


class FreezeLockResult(object):
    def __init__(self, lock_path, source, python):
        self.lock_path = lock_path
        self.source = source
        self.python = python


def _python_info(python_bin):
    cmd = [
        python_bin,
        "-c",
        (
            "import json, sys; "
            "print(json.dumps({"
            "'version': sys.version, "
            "'version_info': list(sys.version_info[:3])"
            "}))"
        ),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            universal_newlines=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"Failed to inspect Python interpreter: {python_bin}") from exc
    return json.loads(completed.stdout)


def _run(cmd, cwd=None):
    try:
        subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            check=True,
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as exc:
        raise BuildError(f"Command failed ({exc.returncode}): {' '.join(cmd)}") from exc


def _sanitize_name(value):
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


SPECIFIER_RE = re.compile(r"^(<=|>=|==|!=|<|>|~=)\s*([0-9]+(?:\.[0-9]+){0,2})(\.\*)?$")
EXACT_PYPI_SPEC_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*==\s*([0-9]+(?:\.[0-9]+){1,2})\s*$")
PYPI_RELEASE_JSON = "https://pypi.org/pypi/{package}/{version}/json"


def _normalize_version(value):
    parts = [int(part) for part in value.split(".") if part]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _compare_tuple_prefix(left, right_text):
    raw_parts = [int(part) for part in right_text.split(".") if part]
    return tuple(left[: len(raw_parts)]) == tuple(raw_parts)


def _version_matches_spec(version, requires_python):
    spec_text = requires_python.strip()
    if not spec_text:
        return True

    for raw_part in spec_text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        match = SPECIFIER_RE.match(part)
        if not match:
            raise BuildError(f"Unsupported Requires-Python specifier: {requires_python}")
        operator, version_text, wildcard = match.groups()
        target = _normalize_version(version_text)

        if wildcard:
            if operator == "==":
                if not _compare_tuple_prefix(version, version_text):
                    return False
                continue
            if operator == "!=":
                if _compare_tuple_prefix(version, version_text):
                    return False
                continue
            raise BuildError(f"Unsupported wildcard specifier: {part}")

        if operator == ">=" and version < target:
            return False
        elif operator == "<=" and version > target:
            return False
        elif operator == ">" and version <= target:
            return False
        elif operator == "<" and version >= target:
            return False
        elif operator == "==" and version != target:
            return False
        elif operator == "!=" and version == target:
            return False
        elif operator == "~=":
            if version < target:
                return False
            segments = [int(part) for part in version_text.split(".") if part]
            if len(segments) <= 2:
                upper = (segments[0] + 1, 0, 0)
            else:
                upper = (segments[0], segments[1] + 1, 0)
            if version >= upper:
                return False

    return True


def _fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"{TOOL_NAME}/{TOOL_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise BuildError(f"Failed to fetch {url}: {exc}") from exc


def _exact_pypi_release_requires_python(source):
    match = EXACT_PYPI_SPEC_RE.match(source)
    if not match:
        return None
    package = match.group(1)
    version = match.group(2)
    payload = _fetch_json(PYPI_RELEASE_JSON.format(package=package, version=version))
    info = payload.get("info", {})
    if not isinstance(info, dict):
        raise BuildError(f"Unexpected release metadata for {package} {version}")
    requires_python = str(info.get("requires_python") or "")
    return package, version, requires_python


def _normalize_source_alias(source):
    stripped = source.strip()

    exact_210 = re.fullmatch(r"(?i)(ansible[-_]core)\s*==\s*(2\.10(?:\.\d+)?)", stripped)
    if exact_210:
        return f"ansible-base=={exact_210.group(2)}"

    mentions_core_210 = re.search(r"(?i)\bansible[-_]core\b", stripped) and re.search(r"\b2\.10(\b|[^\d])", stripped)
    if mentions_core_210:
        raise BuildError(
            "Ansible 2.10 is published on PyPI as 'ansible-base', not 'ansible-core'. "
            f"Use 'ansible-base==2.10.x' instead of '{source}'."
        )

    return source


def _download_artifact(source, python_bin, download_dir, wheelhouse, offline):
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


def _read_member_from_tar(artifact, member_suffix):
    with tarfile.open(artifact, "r:*") as archive:
        for member in archive.getmembers():
            if member.name.endswith(member_suffix) and member.isfile():
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                return extracted.read().decode("utf-8", "replace")
    return None


def _read_member_from_zip(artifact, member_suffix):
    with zipfile.ZipFile(artifact) as archive:
        for member in archive.namelist():
            if member.endswith(member_suffix):
                return archive.read(member).decode("utf-8", "replace")
    return None


def _parse_email_metadata(raw_text):
    return email.message_from_string(raw_text)


def _parse_requirements_text(raw_text):
    requirements = []
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        requirements.append(line)
    return requirements


def _read_metadata_version(metadata_path):
    if metadata_path.suffix == ".dist-info":
        raw_text = (metadata_path / "METADATA").read_text(encoding="utf-8", errors="replace")
    else:
        raw_text = (metadata_path / "PKG-INFO").read_text(encoding="utf-8", errors="replace")
    message = _parse_email_metadata(raw_text)
    return message.get("Name"), message.get("Version")


def _collect_installed_distributions(ansible_dir):
    distributions = []
    for metadata_path in sorted(ansible_dir.glob("*.dist-info")) + sorted(ansible_dir.glob("*.egg-info")):
        if metadata_path.suffix == ".dist-info" and not (metadata_path / "METADATA").exists():
            continue
        if metadata_path.suffix == ".egg-info" and not (metadata_path / "PKG-INFO").exists():
            continue
        name, version = _read_metadata_version(metadata_path)
        if not name or not version:
            continue
        distributions.append(
            {
                "name": name,
                "version": version,
                "metadata_dir": metadata_path.name,
            }
        )
    distributions.sort(key=lambda item: item["name"].lower())
    return distributions


def _inspect_wheel(artifact, input_source):
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
        requires_python=str(message.get("Requires-Python") or ""),
        runtime_requirements=message.get_all("Requires-Dist", []),
    )


def _inspect_sdist(artifact, input_source):
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
        requires_python=str(message.get("Requires-Python") or ""),
        runtime_requirements=runtime_requirements,
    )


def _inspect_artifact(artifact, input_source):
    if artifact.suffix == ".whl":
        return _inspect_wheel(artifact, input_source)
    if artifact.suffix in {".zip", ".gz", ".bz2", ".xz"} or artifact.name.endswith(".tar.gz") or artifact.name.endswith(".tar.bz2") or artifact.name.endswith(".tar.xz"):
        return _inspect_sdist(artifact, input_source)
    raise BuildError(f"Unsupported artifact type: {artifact}")


def _apply_official_controller_support(metadata):
    support = lookup_controller_support(metadata.package_name, metadata.version)
    if support is None:
        return metadata
    metadata.official_controller_min_python = support.minimum_python3
    metadata.official_controller_support = support.official_text
    metadata.official_controller_support_url = support.source_url
    metadata.official_controller_support_note = support.note
    metadata.official_controller_support_note_url = support.note_source_url
    return metadata


def inspect_source(source, python_bin, wheelhouse, offline):
    return _resolve_source_metadata(
        source=source,
        python_bin=python_bin,
        wheelhouse=wheelhouse,
        offline=offline,
        download_dir=None,
    )


def _resolve_source_metadata(source, python_bin, wheelhouse, offline, download_dir):
    source_path = Path(source).expanduser()
    if source_path.exists():
        artifact = source_path.resolve()
    else:
        resolved_source = _normalize_source_alias(source)
        exact_release = _exact_pypi_release_requires_python(resolved_source)
        if exact_release is not None:
            package, version, requires_python = exact_release
            python_info = _python_info(python_bin)
            version_info = python_info["version_info"]
            version_tuple = (int(version_info[0]), int(version_info[1]), int(version_info[2]))
            support = lookup_controller_support(package, version)
            if support is not None:
                official_min_tuple = _normalize_version(support.minimum_python3)
                if version_tuple < official_min_tuple:
                    message = (
                        f"Python {version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]} is lower than the documented "
                        f"control-node minimum for {package} {version}: {support.minimum_python3}+"
                    )
                    if support.official_text:
                        message += f" (official support text: {support.official_text})"
                    if support.source_url:
                        message += f". Source: {support.source_url}"
                    raise BuildError(message)
            if requires_python and not _version_matches_spec(version_tuple, requires_python):
                if support is not None:
                    message = (
                        f"Python {version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]} meets the documented "
                        f"control-node minimum for {package} {version} ({support.minimum_python3}+), but the "
                        f"downloadable package artifact declares a stricter Requires-Python: {requires_python}. "
                        "This affects direct pip download/install for that artifact."
                    )
                    if support.source_url:
                        message += f" Official docs: {support.source_url}"
                    raise BuildError(message)
                raise BuildError(
                    f"Python {version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]} does not satisfy "
                    f"{package} {version} package metadata Requires-Python: {requires_python}"
                )
        if download_dir is None:
            with tempfile.TemporaryDirectory(prefix="portable-source-") as temp_dir:
                artifact = _download_artifact(
                    resolved_source,
                    python_bin=python_bin,
                    download_dir=Path(temp_dir),
                    wheelhouse=wheelhouse,
                    offline=offline,
                )
                return _apply_official_controller_support(_inspect_artifact(artifact, source))
        artifact = _download_artifact(
            resolved_source,
            python_bin=python_bin,
            download_dir=download_dir,
            wheelhouse=wheelhouse,
            offline=offline,
        )

    return _apply_official_controller_support(_inspect_artifact(artifact, source))


def _validate_python_for_source(metadata, python_bin):
    python_info = _python_info(python_bin)
    version_info = python_info["version_info"]
    version_tuple = (int(version_info[0]), int(version_info[1]), int(version_info[2]))
    official_min = metadata.official_controller_min_python.strip()
    if official_min:
        official_min_tuple = _normalize_version(official_min)
        if version_tuple < official_min_tuple:
            message = (
                f"Python {version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]} is lower than the documented "
                f"control-node minimum for {metadata.package_name} {metadata.version}: "
                f"{metadata.official_controller_min_python}+"
            )
            if metadata.official_controller_support:
                message += f" (official support text: {metadata.official_controller_support})"
            if metadata.official_controller_support_url:
                message += f". Source: {metadata.official_controller_support_url}"
            raise BuildError(message)
    requires_python = metadata.requires_python.strip()
    if requires_python and not _version_matches_spec(version_tuple, requires_python):
        if official_min:
            message = (
                f"Python {version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]} meets the documented control-node "
                f"minimum for {metadata.package_name} {metadata.version} ({metadata.official_controller_min_python}+), "
                f"but the downloadable package artifact declares a stricter Requires-Python: {requires_python}. "
                "This affects direct pip download/install for that artifact."
            )
            if metadata.official_controller_support_url:
                message += f" Official docs: {metadata.official_controller_support_url}"
            raise BuildError(message)
        raise BuildError(
            f"Python {version_tuple[0]}.{version_tuple[1]}.{version_tuple[2]} does not satisfy "
            f"{metadata.package_name} {metadata.version} package metadata Requires-Python: {requires_python}"
        )
    return python_info


def _install_with_pip(
    python_bin,
    target,
    packages=None,
    requirement_files=None,
    constraint_file=None,
    wheelhouse=None,
    offline=False,
):
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


def _discover_ansible_commands(ansible_dir):
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


def _write_quickstart(bundle_dir, commands, metadata):
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


def _write_bundle_notices(bundle_dir, metadata):
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


def _create_command_symlinks(bundle_dir, commands):
    for command in commands:
        if command == "ansible":
            continue
        link = bundle_dir / command
        if link.exists() or link.is_symlink():
            link.unlink()
        os.symlink("ansible", link)


def _remove_matching(root, pattern):
    for path in root.rglob(pattern):
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()


def _prune_bundle(ansible_dir, strip_metadata):
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
    bundle_dir,
    metadata,
    commands,
    python_bin,
    python_info,
    build_extras,
    installed_distributions,
):
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
            "version": python_info["version"],
            "version_info": python_info["version_info"],
        },
        "bundle": {
            "name": bundle_dir.name,
            "commands": commands,
            "ansible_dir": "ansible",
            "extras_dir": "ansible/extras",
        },
        "build_extras": build_extras,
        "installed_distributions": installed_distributions,
        "extra_installs": [],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return manifest_path


def _load_manifest(manifest_path):
    if not manifest_path.exists():
        raise BuildError(f"Missing manifest file: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _save_manifest(manifest_path, manifest):
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def _compile_launcher(python_bin, ansible_dir):
    py_compile.compile(str(ansible_dir / "__main__.py"), doraise=True)


def _self_test_bundle(python_bin, bundle_dir):
    _run([python_bin, str(bundle_dir / "ansible"), "localhost", "-m", "ping"])


def _create_archive(bundle_dir, compression):
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


def _write_lock_file(lock_path, metadata, python_info, installed_distributions):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Lock file for {metadata.package_name} {metadata.version}",
        f"# Generated by {TOOL_NAME} {TOOL_VERSION}",
        f"# Source: {metadata.input_source}",
        f"# Python: {python_info['version'].splitlines()[0]}",
        "",
    ]
    lines.extend(f"{item['name']}=={item['version']}" for item in installed_distributions)
    lock_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_portable_bundle(args):
    with tempfile.TemporaryDirectory(prefix="portable-build-") as temp_dir:
        temp_root = Path(temp_dir)
        metadata = _resolve_source_metadata(
            source=args.source,
            python_bin=args.python,
            wheelhouse=args.wheelhouse,
            offline=args.offline,
            download_dir=temp_root / "downloads",
        )
        python_info = _validate_python_for_source(metadata, args.python)
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
            constraint_file=args.build_constraint,
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
        installed_distributions = _collect_installed_distributions(ansible_dir)
        _create_command_symlinks(stage_root, commands)
        _write_quickstart(stage_root, commands, metadata)
        _write_bundle_notices(stage_root, metadata)
        manifest_path = _write_manifest(
            bundle_dir=stage_root,
            metadata=metadata,
            commands=commands,
            python_bin=args.python,
            python_info=python_info,
            build_extras={
                "build_constraint_file": str(args.build_constraint) if args.build_constraint else None,
                "packages": args.extra_package,
                "requirement_files": [str(path) for path in args.extra_requirements],
                "constraint_file": str(args.constraint) if args.constraint else None,
            },
            installed_distributions=installed_distributions,
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


def freeze_build_lock(args):
    with tempfile.TemporaryDirectory(prefix="portable-lock-") as temp_dir:
        temp_root = Path(temp_dir)
        metadata = _resolve_source_metadata(
            source=args.source,
            python_bin=args.python,
            wheelhouse=args.wheelhouse,
            offline=args.offline,
            download_dir=temp_root / "downloads",
        )
        python_info = _validate_python_for_source(metadata, args.python)
        target = temp_root / "resolved"
        target.mkdir(parents=True)
        _install_with_pip(
            python_bin=args.python,
            target=target,
            packages=[str(metadata.artifact_path)],
            constraint_file=args.build_constraint,
            wheelhouse=args.wheelhouse,
            offline=args.offline,
        )
        installed_distributions = _collect_installed_distributions(target)
        if not installed_distributions:
            raise BuildError(f"No installed distributions found while resolving lock for {args.source}")
        lock_path = args.output.resolve()
        _write_lock_file(lock_path, metadata, python_info, installed_distributions)
        return FreezeLockResult(
            lock_path=lock_path,
            source=metadata,
            python=python_info,
        )


def _bundle_paths(bundle_dir):
    bundle_root = bundle_dir.resolve()
    ansible_dir = bundle_root / "ansible"
    extras_dir = ansible_dir / "extras"
    manifest_path = bundle_root / MANIFEST_FILE
    if not ansible_dir.is_dir():
        raise BuildError(f"Invalid bundle. Missing directory: {ansible_dir}")
    extras_dir.mkdir(parents=True, exist_ok=True)
    return ansible_dir, extras_dir, manifest_path


def install_bundle_extras(args):
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
