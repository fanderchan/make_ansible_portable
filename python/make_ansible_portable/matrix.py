from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from .builder import BuildError, build_portable_bundle

AUTO_DISCOVER_PYTHONS = (
    "python3",
    "python3.9",
    "python3.10",
    "python3.11",
    "python3.12",
    "python3.13",
    "python3.14",
)
README_BEGIN_MARKER = "<!-- BEGIN TESTED MATRIX -->"
README_END_MARKER = "<!-- END TESTED MATRIX -->"
README_LANGUAGE_EN = "en"
README_LANGUAGE_ZH_CN = "zh-CN"
STATUS_PASSED = "passed"
STATUS_BUILD_FAILED = "build_failed"
STATUS_MISSING_PYTHON = "missing_python"
PYPI_PROJECT_JSON = "https://pypi.org/pypi/{package}/json"
PYPI_RELEASE_JSON = "https://pypi.org/pypi/{package}/{version}/json"
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
MINOR_RE = re.compile(r"^(\d+)\.(\d+)$")
SPECIFIER_RE = re.compile(r"^(<=|>=|==|!=|<|>|~=)\s*([0-9]+(?:\.[0-9]+){0,2})(\.\*)?$")


@dataclass(frozen=True)
class PythonCandidate:
    executable: str
    version_tuple: tuple[int, int, int]
    version_text: str


@dataclass
class ReleaseInfo:
    minor: str
    package: str
    version: str
    requires_python: str
    project_url: str
    sdist_url: str | None
    wheel_url: str | None


@dataclass
class MatrixEntry:
    minor: str
    package: str
    version: str
    status: str
    requires_python: str
    python_version: str | None
    python_executable: str | None
    project_url: str
    sdist_url: str | None
    wheel_url: str | None
    bundle_dir: str | None
    note: str | None


@dataclass
class MatrixRefreshResult:
    readme_path: Path
    results_json_path: Path
    entries: list[MatrixEntry]

    @property
    def all_passed(self) -> bool:
        return all(entry.status == STATUS_PASSED for entry in self.entries)


def _fetch_json(url: str) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "make-ansible-portable-test-matrix/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise BuildError(f"Failed to fetch {url}: {exc}") from exc


def _parse_minor(value: str) -> tuple[int, int]:
    match = MINOR_RE.match(value.strip())
    if not match:
        raise BuildError(f"Invalid minor version: {value}. Expected format like 2.10")
    return int(match.group(1)), int(match.group(2))


def _format_minor(value: tuple[int, int]) -> str:
    return f"{value[0]}.{value[1]}"


def _detect_readme_language(readme_path: Path) -> str:
    name = readme_path.name.lower()
    if ".zh" in name or "zh-cn" in name or "zh_cn" in name:
        return README_LANGUAGE_ZH_CN
    return README_LANGUAGE_EN


def _parse_version_tuple(value: str) -> tuple[int, int, int] | None:
    match = VERSION_RE.match(value.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _normalize_version(value: str) -> tuple[int, int, int]:
    parts = [int(part) for part in value.split(".") if part]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _compare_tuple_prefix(left: tuple[int, int, int], right_text: str) -> bool:
    raw_parts = [int(part) for part in right_text.split(".") if part]
    return tuple(left[: len(raw_parts)]) == tuple(raw_parts)


def _version_matches_spec(version: tuple[int, int, int], requires_python: str) -> bool:
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


def _probe_python(python_bin: str) -> PythonCandidate:
    try:
        result = subprocess.run(
            [python_bin, "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')"],
            check=True,
            text=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise BuildError(f"Failed to probe Python executable: {python_bin}") from exc

    version_text = result.stdout.strip()
    version_tuple = _normalize_version(version_text)
    resolved = shutil.which(python_bin) if "/" not in python_bin else python_bin
    executable = str(Path(resolved or python_bin).expanduser())
    return PythonCandidate(
        executable=executable,
        version_tuple=version_tuple,
        version_text=version_text,
    )


def _discover_python_candidates(explicit: list[str]) -> list[PythonCandidate]:
    seen: set[str] = set()
    candidates: list[PythonCandidate] = []

    def add_candidate(raw_value: str, *, required: bool) -> None:
        resolved = shutil.which(raw_value) if "/" not in raw_value else raw_value
        if not resolved:
            if required:
                raise BuildError(f"Python executable not found: {raw_value}")
            return
        path = str(Path(resolved).expanduser())
        if path in seen:
            return
        candidate = _probe_python(path)
        seen.add(candidate.executable)
        candidates.append(candidate)

    for value in explicit:
        add_candidate(value, required=True)
    for value in AUTO_DISCOVER_PYTHONS:
        add_candidate(value, required=False)

    candidates.sort(key=lambda item: item.version_tuple)
    if not candidates:
        raise BuildError("No usable Python executables found. Provide --python-candidate.")
    return candidates


def _parse_python_overrides(raw_values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for raw_value in raw_values:
        if "=" not in raw_value:
            raise BuildError(f"Invalid --python-override value: {raw_value}. Expected 2.18=/path/to/python")
        minor, executable = raw_value.split("=", 1)
        normalized_minor = _format_minor(_parse_minor(minor))
        candidate = _probe_python(executable.strip())
        overrides[normalized_minor] = candidate.executable
    return overrides


def _pick_python_for_release(
    *,
    release: ReleaseInfo,
    candidates: list[PythonCandidate],
    overrides: dict[str, str],
) -> PythonCandidate | None:
    override = overrides.get(release.minor)
    if override:
        return _probe_python(override)

    for candidate in candidates:
        if _version_matches_spec(candidate.version_tuple, release.requires_python):
            return candidate
    return None


def _latest_releases_for_range(
    *,
    start_minor: tuple[int, int],
    end_minor: tuple[int, int] | None,
) -> list[ReleaseInfo]:
    package_windows = [
        ("ansible-base", (2, 10), (2, 10)),
        ("ansible-core", (2, 11), None),
    ]
    latest: dict[tuple[int, int], tuple[str, str]] = {}

    for package, min_minor, max_minor in package_windows:
        project = _fetch_json(PYPI_PROJECT_JSON.format(package=package))
        releases = project.get("releases", {})
        if not isinstance(releases, dict):
            raise BuildError(f"Unexpected PyPI payload for package: {package}")

        for raw_version in releases:
            version_tuple = _parse_version_tuple(str(raw_version))
            if version_tuple is None:
                continue
            minor = version_tuple[:2]
            if minor < start_minor:
                continue
            if end_minor is not None and minor > end_minor:
                continue
            if minor < min_minor:
                continue
            if max_minor is not None and minor > max_minor:
                continue

            current = latest.get(minor)
            if current is None or version_tuple > _parse_version_tuple(current[1]):
                latest[minor] = (package, raw_version)

    releases: list[ReleaseInfo] = []
    for minor in sorted(latest):
        package, version = latest[minor]
        payload = _fetch_json(PYPI_RELEASE_JSON.format(package=package, version=version))
        info = payload.get("info", {})
        urls = payload.get("urls", [])
        if not isinstance(info, dict) or not isinstance(urls, list):
            raise BuildError(f"Unexpected release payload for {package} {version}")

        sdist_url = None
        wheel_url = None
        for file_info in urls:
            if not isinstance(file_info, dict):
                continue
            if file_info.get("packagetype") == "sdist" and not sdist_url:
                sdist_url = file_info.get("url")
            if file_info.get("packagetype") == "bdist_wheel" and not wheel_url:
                wheel_url = file_info.get("url")

        releases.append(
            ReleaseInfo(
                minor=_format_minor(minor),
                package=package,
                version=version,
                requires_python=str(info.get("requires_python") or ""),
                project_url=f"https://pypi.org/project/{package}/{version}/",
                sdist_url=sdist_url,
                wheel_url=wheel_url,
            )
        )

    return releases


def _bundle_name(package: str, version: str) -> str:
    return f"{package}--{version.replace('.', '-')}"


def _build_release(
    *,
    release: ReleaseInfo,
    python_candidate: PythonCandidate,
    output_dir: Path,
    wheelhouse: Path | None,
    offline: bool,
) -> MatrixEntry:
    source = f"{release.package}=={release.version}"
    args = SimpleNamespace(
        source=source,
        bundle_name=_bundle_name(release.package, release.version),
        output_dir=output_dir,
        compression="gz",
        clean_output=True,
        skip_archive=True,
        skip_self_test=False,
        build_constraint=None,
        no_auto_build_constraint=False,
        strip_metadata=False,
        without_vault=False,
        without_yaml_c_extension=False,
        python=python_candidate.executable,
        wheelhouse=wheelhouse,
        offline=offline,
        extra_package=[],
        extra_requirements=[],
        constraint=None,
        extra_collection=[],
        extra_collection_requirements=[],
    )

    try:
        result = build_portable_bundle(args)
        return MatrixEntry(
            minor=release.minor,
            package=release.package,
            version=release.version,
            status=STATUS_PASSED,
            requires_python=release.requires_python,
            python_version=python_candidate.version_text,
            python_executable=python_candidate.executable,
            project_url=release.project_url,
            sdist_url=release.sdist_url,
            wheel_url=release.wheel_url,
            bundle_dir=str(result.bundle_dir),
            note=None,
        )
    except BuildError as exc:
        return MatrixEntry(
            minor=release.minor,
            package=release.package,
            version=release.version,
            status=STATUS_BUILD_FAILED,
            requires_python=release.requires_python,
            python_version=python_candidate.version_text,
            python_executable=python_candidate.executable,
            project_url=release.project_url,
            sdist_url=release.sdist_url,
            wheel_url=release.wheel_url,
            bundle_dir=None,
            note=str(exc),
        )


def _markdown_links(entry: MatrixEntry) -> str:
    links = [f"[PyPI]({entry.project_url})"]
    if entry.sdist_url:
        links.append(f"[sdist]({entry.sdist_url})")
    if entry.wheel_url:
        links.append(f"[wheel]({entry.wheel_url})")
    return " · ".join(links)


def _group_minors_by_python(entries: list[MatrixEntry]) -> list[tuple[str, list[str]]]:
    groups: dict[str, list[str]] = {}
    for entry in entries:
        if entry.status != STATUS_PASSED or not entry.python_version:
            continue
        groups.setdefault(entry.python_version, []).append(entry.minor)

    def sort_key(version_text: str) -> tuple[int, int, int]:
        return _normalize_version(version_text)

    lines: list[tuple[str, list[str]]] = []
    for version_text in sorted(groups, key=sort_key):
        minors = sorted(groups[version_text], key=_parse_minor)
        lines.append((version_text, minors))
    return lines


def _render_environment_lines(
    entries: list[MatrixEntry],
    *,
    language: str,
) -> list[str]:
    grouped = _group_minors_by_python(entries)
    if not grouped:
        if language == README_LANGUAGE_ZH_CN:
            return ["- 当前没有任何版本通过测试"]
        return ["- No versions passed in the current run"]

    lines: list[str] = []
    for version_text, minors in grouped:
        if len(minors) == 1:
            minor_text = minors[0]
        elif language == README_LANGUAGE_ZH_CN:
            minor_text = f"{minors[0]} 到 {minors[-1]}"
        else:
            minor_text = f"{minors[0]} to {minors[-1]}"

        if language == README_LANGUAGE_ZH_CN:
            lines.append(f"- `Python {version_text}`：用于 `{minor_text}`")
        else:
            lines.append(f"- `Python {version_text}`: used for `{minor_text}`")
    return lines


def _failure_notes(entries: list[MatrixEntry]) -> list[str]:
    notes: list[str] = []
    for entry in entries:
        if entry.status == STATUS_PASSED or not entry.note:
            continue
        notes.append(f"- `{entry.minor}`: {entry.note}")
    return notes


def _render_status(status: str, *, language: str) -> str:
    if language == README_LANGUAGE_ZH_CN:
        labels = {
            STATUS_PASSED: "已测通过",
            STATUS_BUILD_FAILED: "构建失败",
            STATUS_MISSING_PYTHON: "缺少匹配 Python",
        }
    else:
        labels = {
            STATUS_PASSED: "Passed",
            STATUS_BUILD_FAILED: "Build failed",
            STATUS_MISSING_PYTHON: "No matching Python",
        }
    return labels.get(status, status)


def _render_matrix_body(
    *,
    entries: list[MatrixEntry],
    results_json_display: str,
    language: str,
) -> str:
    generated_date = datetime.now().date().isoformat()
    environment_lines = _render_environment_lines(entries, language=language)

    if language == README_LANGUAGE_ZH_CN:
        lines = [
            "这段内容由 `./refresh-tested-matrix.sh` 自动生成。  ",
            f"测试时间：{generated_date}",
            "",
            "测试环境：",
            "",
            *environment_lines,
            "",
            "判定标准：",
            "",
            "- `已测通过`：`./build.sh --source <spec> --python <matching-python> --skip-archive --clean-output` 成功",
            "- 并且自动 `localhost -m ping` 自测成功",
            "",
            "说明：`2.10` 这一代官方包名还是 `ansible-base`，从 `2.11` 起才是 `ansible-core`。",
            "",
            "| Minor | Package | Final patch | 状态 | 测试 Python | Requires-Python | 官方下载 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    else:
        lines = [
            "Generated by `./refresh-tested-matrix.sh`.  ",
            f"Test date: {generated_date}",
            "",
            "Test environment:",
            "",
            *environment_lines,
            "",
            "Pass criteria:",
            "",
            "- `Passed`: `./build.sh --source <spec> --python <matching-python> --skip-archive --clean-output` succeeds",
            "- and the automatic `localhost -m ping` self-test succeeds",
            "",
            "Note: the official PyPI package name is still `ansible-base` for `2.10`; it changes to `ansible-core` starting from `2.11`.",
            "",
            "| Minor | Package | Final patch | Status | Test Python | Requires-Python | Official downloads |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]

    for entry in entries:
        python_text = f"`{entry.python_version}`" if entry.python_version else "-"
        requires_python = f"`{entry.requires_python}`" if entry.requires_python else "-"
        lines.append(
            f"| {entry.minor} | {entry.package} | {entry.version} | {_render_status(entry.status, language=language)} | {python_text} | {requires_python} | {_markdown_links(entry)} |"
        )

    if language == README_LANGUAGE_ZH_CN:
        lines.extend(
            [
                "",
                "补充说明：",
                "",
                f"- 最近一次执行的详细 JSON 结果会写到 `{results_json_display}`。",
                "- 如果某一行不是 `已测通过`，准备好匹配的 Python 解释器后重新执行 `./refresh-tested-matrix.sh`。",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Additional notes:",
                "",
                f"- The detailed JSON result from the most recent run is written to `{results_json_display}`.",
                "- If any row is not `Passed`, prepare a matching Python interpreter and rerun `./refresh-tested-matrix.sh`.",
            ]
        )
    lines.extend(_failure_notes(entries))
    return "\n".join(lines) + "\n"


def _replace_readme_section(readme_path: Path, matrix_body: str) -> None:
    text = readme_path.read_text(encoding="utf-8")
    begin_token = f"{README_BEGIN_MARKER}\n"
    end_token = f"\n{README_END_MARKER}"
    if begin_token not in text or README_END_MARKER not in text:
        raise BuildError(
            f"README markers not found in {readme_path}. Expected {README_BEGIN_MARKER} and {README_END_MARKER}."
        )
    before, remainder = text.split(begin_token, 1)
    _, after = remainder.split(end_token, 1)
    updated = before + begin_token + matrix_body.rstrip("\n") + end_token + after
    readme_path.write_text(updated, encoding="utf-8")


def _write_results_json(results_path: Path, entries: list[MatrixEntry]) -> None:
    results_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generator_python": sys.version,
        "entries": [asdict(entry) for entry in entries],
    }
    results_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def refresh_tested_matrix(args) -> MatrixRefreshResult:
    start_minor = _parse_minor(args.start_minor)
    end_minor = _parse_minor(args.end_minor) if args.end_minor else None
    if end_minor is not None and end_minor < start_minor:
        raise BuildError("--end-minor must be greater than or equal to --start-minor")

    releases = _latest_releases_for_range(start_minor=start_minor, end_minor=end_minor)
    if not releases:
        raise BuildError("No stable releases found for the requested minor range.")

    candidates = _discover_python_candidates(args.python_candidate)
    overrides = _parse_python_overrides(args.python_override)
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    results_json_path = (args.results_json or (output_dir / "tested-matrix.json")).resolve()

    entries: list[MatrixEntry] = []
    for release in releases:
        python_candidate = _pick_python_for_release(
            release=release,
            candidates=candidates,
            overrides=overrides,
        )
        if python_candidate is None:
            entries.append(
                MatrixEntry(
                    minor=release.minor,
                    package=release.package,
                    version=release.version,
                    status=STATUS_MISSING_PYTHON,
                    requires_python=release.requires_python,
                    python_version=None,
                    python_executable=None,
                    project_url=release.project_url,
                    sdist_url=release.sdist_url,
                    wheel_url=release.wheel_url,
                    bundle_dir=None,
                    note=f"No Python candidate satisfies Requires-Python: {release.requires_python or '(empty)'}",
                )
            )
            continue
        entries.append(
            _build_release(
                release=release,
                python_candidate=python_candidate,
                output_dir=output_dir,
                wheelhouse=args.wheelhouse,
                offline=args.offline,
            )
        )

    _write_results_json(results_json_path, entries)
    if not args.skip_readme_update:
        readme_path = args.readme.resolve()
        language = _detect_readme_language(readme_path)
        try:
            results_json_display = str(results_json_path.relative_to(readme_path.parent))
        except ValueError:
            results_json_display = str(results_json_path)
        matrix_body = _render_matrix_body(
            entries=entries,
            results_json_display=results_json_display,
            language=language,
        )
        _replace_readme_section(readme_path, matrix_body)

    return MatrixRefreshResult(
        readme_path=args.readme.resolve(),
        results_json_path=results_json_path,
        entries=entries,
    )
