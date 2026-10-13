import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str
    previous_path: str | None = None
    content: str = ""


@dataclass(frozen=True)
class PullRequestDiff:
    project_path: Path
    base_ref: str
    head_ref: str
    diff: str
    changed_files: tuple[ChangedFile, ...]


def load_pull_request_diff(
    project_path: Path,
    base_ref: str,
    head_ref: str,
    *,
    max_diff_chars: int,
    max_file_chars: int,
) -> PullRequestDiff:
    resolved_project_path = project_path.expanduser().resolve()
    if not resolved_project_path.is_dir():
        raise RuntimeError(f"Project path does not exist or is not a directory: {resolved_project_path}")

    revision_range = f"{base_ref}...{head_ref}"
    diff = _run_git(
        resolved_project_path,
        "diff",
        "--find-renames",
        "--unified=80",
        revision_range,
    )
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + "\n\n[diff truncated]\n"

    name_status = _run_git(
        resolved_project_path,
        "diff",
        "--name-status",
        "--find-renames",
        revision_range,
    )
    changed_files = tuple(
        _with_file_content(resolved_project_path, changed_file, max_file_chars)
        for changed_file in _parse_name_status(name_status)
    )
    return PullRequestDiff(
        project_path=resolved_project_path,
        base_ref=base_ref,
        head_ref=head_ref,
        diff=diff,
        changed_files=changed_files,
    )


def _parse_name_status(name_status: str) -> list[ChangedFile]:
    files: list[ChangedFile] = []
    for raw_line in name_status.splitlines():
        if not raw_line.strip():
            continue
        parts = raw_line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) >= 3:
            files.append(ChangedFile(path=parts[2], previous_path=parts[1], status=status))
            continue
        if len(parts) >= 2:
            files.append(ChangedFile(path=parts[1], status=status))
    return files


def _with_file_content(project_path: Path, changed_file: ChangedFile, max_file_chars: int) -> ChangedFile:
    if changed_file.status.startswith("D"):
        return changed_file
    file_path = (project_path / changed_file.path).resolve()
    try:
        file_path.relative_to(project_path)
    except ValueError:
        return changed_file
    if not file_path.is_file():
        return changed_file
    try:
        raw_bytes = file_path.read_bytes()
    except OSError:
        return changed_file
    if b"\x00" in raw_bytes[:4096]:
        return changed_file
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return changed_file
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    if len(content) > max_file_chars:
        content = content[:max_file_chars] + "\n\n[file content truncated]\n"
    return ChangedFile(
        path=changed_file.path,
        previous_path=changed_file.previous_path,
        status=changed_file.status,
        content=content,
    )


def _run_git(project_path: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(project_path), *args),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise RuntimeError(message)
    return result.stdout
