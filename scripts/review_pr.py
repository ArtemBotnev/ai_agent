#!/usr/bin/env python3
import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from application.code_review.diff_loader import load_pull_request_diff
from application.code_review.review_service import CodeReviewService, with_project_path
from application.chat.agent_error import AgentError
from config.project_assistant_config import ProjectSourceConfig, load_project_assistant_config
from main import build_chat_service, format_agent_error


def main() -> None:
    args = parse_args()
    project_path = args.project_path.expanduser().resolve()
    base_ref = args.base_ref or args.base_sha or _github_event_value("base.sha") or os.getenv("GITHUB_BASE_REF")
    head_ref = args.head_ref or args.head_sha or _github_event_value("head.sha") or os.getenv("GITHUB_HEAD_REF")
    if not base_ref or not head_ref:
        raise RuntimeError("Provide --base-ref/--base-sha and --head-ref/--head-sha, or run inside a pull_request action.")

    base_config = load_project_assistant_config()
    config = with_project_path(
        base_config,
        project_path,
        index_file=args.index_file,
        source=ProjectSourceConfig(
            source_paths=(Path("."),),
            exclude_dirs=base_config.source.exclude_dirs,
            exclude_globs=base_config.source.exclude_globs,
            max_file_bytes=base_config.source.max_file_bytes,
        ),
    )
    review_service = CodeReviewService(config)
    if not args.skip_build_rag:
        result = review_service.rag_index.build()
        print(
            "Project RAG built: "
            f"documents={result.documents}, chunks={result.chunks}, index={result.index_file}",
            file=sys.stderr,
        )

    pull_request_diff = load_pull_request_diff(
        project_path,
        base_ref,
        head_ref,
        max_diff_chars=config.review.max_diff_chars,
        max_file_chars=config.review.max_file_chars,
    )
    request = review_service.prepare_request(pull_request_diff)
    chat_service = build_chat_service()
    try:
        answer = chat_service.answer_once(request.prompt, context=request.context)
    except AgentError as error:
        raise RuntimeError(format_agent_error(error)) from error

    review_text = answer.text.strip() + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(review_text, encoding="utf-8")
    else:
        print(review_text)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Review a GitHub pull request diff with the project assistant.")
    parser.add_argument("--project-path", type=Path, default=Path.cwd(), help="Path to the checked out target repository.")
    parser.add_argument("--base-ref", help="Base git ref for local review, for example origin/main.")
    parser.add_argument("--head-ref", help="Head git ref for local review, for example HEAD.")
    parser.add_argument("--base-sha", help="Base commit SHA from GitHub pull_request event.")
    parser.add_argument("--head-sha", help="Head commit SHA from GitHub pull_request event.")
    parser.add_argument("--index-file", type=Path, help="SQLite RAG index file to create or reuse.")
    parser.add_argument("--output", type=Path, help="Write Markdown review to this file.")
    parser.add_argument("--skip-build-rag", action="store_true", help="Reuse an existing RAG index.")
    return parser.parse_args()


def _github_event_value(path: str) -> str | None:
    event_path = os.getenv("GITHUB_EVENT_PATH")
    if not event_path:
        return None
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value: object = payload.get("pull_request", payload)
    for key in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(f"AI review failed: {error}", file=sys.stderr)
        sys.exit(1)
