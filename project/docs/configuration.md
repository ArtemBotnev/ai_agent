# Configuration

LLM provider settings are stored in `agent_config/llm.yaml`. Private cloud endpoint values can be overlaid from `agent_config/llm.local.yaml`, which is ignored by git.

Project assistant settings are stored in `agent_config/project_assistant.local.yaml`, using `agent_config/project_assistant.example.yaml` as the committed template.

Important project assistant fields:

- `project_path` is the absolute path to the local repository the assistant should answer questions about.
- `docs_paths` is kept for backwards-compatible documentation-oriented configs.
- `source.paths` lists text files or directories relative to `project_path` that should be indexed. Use `.` to index a whole project.
- `source.exclude_dirs` excludes runtime and dependency directories from recursive indexing.
- `source.exclude_globs` excludes local config, binary files, generated artifacts, archives, and database files.
- `source.max_file_bytes` limits the maximum indexed file size.
- `index_file` is the SQLite RAG index location. The default is `rag/project_rag_index.sqlite`, outside chat history.
- `mcp.enabled` switches project context access from the local adapter to MCP.
- `mcp.server_url` is the MCP Streamable HTTP server URL, for example `http://localhost:8000`.
- `mcp.timeout_seconds` controls MCP request timeout.
- `github.mcp` is reserved for GitHub-specific MCP context and is separate from the local project MCP section.
- `embedding.provider` selects the embedding implementation. The normal value is `ollama`.
- `embedding.model` is the Ollama embedding model, for example `nomic-embed-text`.
- `retrieval.top_k` controls how many documentation chunks are passed into `/help`.
- `review.max_diff_chars`, `review.max_file_chars`, `review.top_k`, and `review.language` tune pull request review context.
- `ollama.timeout_seconds` in `agent_config/llm.yaml` controls the non-streaming Ollama chat timeout. PR review usually needs a higher value than normal chat.

Before building the project RAG index, run `scripts/start_project_ollama.sh`. The script reads the project assistant config, starts Ollama on the configured base URL, and pulls the configured embedding model.

## GitHub Review Workflow

The committed `.github/workflows/ai-code-review.yml` can run directly in this repository or be called from another repository as a reusable workflow. It expects a self-hosted runner with Ollama available.

Caller repository example:

```yaml
name: AI Code Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  ai-review:
    uses: your-org/ai_second/.github/workflows/ai-code-review.yml@main
    with:
      reviewer_repository: your-org/ai_second
```

The workflow passes GitHub PR base/head SHAs to `scripts/review_pr.py`. The script can also be run locally with `--project-path`, `--base-ref`, and `--head-ref`.
