# AI Second Developer Assistant

AI Second is a Python CLI and PyQt assistant project. It supports OpenAI, local Ollama, and Ollama-compatible cloud providers. The assistant keeps chat history, summaries, sticky facts, working memory, long-term memory, user profile data, and branching conversation state.

## Main Folders

- `main.py` builds the configured chat service and runs the CLI commands.
- `agent.py` contains OpenAI and Ollama-compatible LLM clients plus simple workflow agents.
- `domain` contains domain models such as messages, branches, memory, summaries, user profiles, and invariants.
- `application` contains chat orchestration, memory extraction, summarization, project help, and task workflow interfaces.
- `infrastructure` contains JSON and Markdown repositories plus local project context adapters.
- `config` loads YAML configuration for LLM and project assistant settings.
- `agent_config` stores committed examples and safe public defaults for prompts, provider settings, profiles, and invariants.
- `ui` contains the PyQt application.
- `web` contains the web server entry point.

## CLI Commands

- `/provider` shows or switches the active LLM provider.
- `/model` shows or switches the active model for the current provider.
- `/strategy` shows or switches the conversation context strategy.
- `/clear` clears context for the active strategy.
- `/branch`, `/checkpoint`, and `/new-branch <name>` manage conversation branches.
- `/project` shows the configured project assistant target and current git branch.
- `/project-rag build` builds a local RAG index from project documentation.
- `/project-rag status` shows the current project RAG index status.
- `/help <question>` answers questions about the connected project using the RAG index and project context.

The PyQt UI also supports the project assistant commands typed into the normal message input:

- `/project`
- `/project-rag build`
- `/project-rag status`
- `/help <question>`

The UI also has a `Собрать RAG` button that runs `/project-rag build`.

## Project Assistant

The project assistant reads its private runtime configuration from `agent_config/project_assistant.local.yaml`. The committed example is `agent_config/project_assistant.example.yaml`.

The configured `project_path` points to the local repository being documented. By default the RAG source paths are `README.md` and `project/docs`. Embeddings are created through Ollama using the configured embedding model. The SQLite RAG index is stored outside chat history, under `rag/project_rag_index.sqlite`.

When `project_assistant.mcp.enabled` is `true`, project context such as the current git branch is loaded through the configured MCP Streamable HTTP server. The example MCP URL is `http://localhost:8000`.

Use `scripts/start_project_ollama.sh` to start Ollama and pull the configured embedding model before running `/project-rag build`.

The local project context adapter currently exposes the current git branch. It is intentionally isolated so it can later be replaced by a real MCP client without changing `/help` and RAG command behavior.
