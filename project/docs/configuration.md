# Configuration

LLM provider settings are stored in `agent_config/llm.yaml`. Private cloud endpoint values can be overlaid from `agent_config/llm.local.yaml`, which is ignored by git.

Project assistant settings are stored in `agent_config/project_assistant.local.yaml`, using `agent_config/project_assistant.example.yaml` as the committed template.

Important project assistant fields:

- `project_path` is the absolute path to the local repository the assistant should answer questions about.
- `docs_paths` lists documentation files or directories relative to `project_path`.
- `index_file` is the SQLite RAG index location. The default is `rag/project_rag_index.sqlite`, outside chat history.
- `mcp.enabled` switches project context access from the local adapter to MCP.
- `mcp.server_url` is the MCP Streamable HTTP server URL, for example `http://localhost:8000`.
- `mcp.timeout_seconds` controls MCP request timeout.
- `embedding.provider` selects the embedding implementation. The normal value is `ollama`.
- `embedding.model` is the Ollama embedding model, for example `nomic-embed-text`.
- `retrieval.top_k` controls how many documentation chunks are passed into `/help`.

Before building the project RAG index, run `scripts/start_project_ollama.sh`. The script reads the project assistant config, starts Ollama on the configured base URL, and pulls the configured embedding model.
