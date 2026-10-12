# Architecture

The project follows a layered structure.

`domain` stores pure data models and domain rules. It does not own persistence or provider-specific LLM behavior.

`application` coordinates use cases. Chat orchestration lives in `application/chat`, memory use cases live in `application/memory`, summarization lives in `application/summary`, and project documentation help lives in `application/project_help`.

`infrastructure` contains adapters for storage and external project context. JSON repositories persist chat history, memory, facts, summaries, and branches. Markdown repositories persist user profile and invariants.

`config` loads YAML configuration and converts it into typed dataclasses used by the runtime.

`main.py` wires the dependencies together and owns CLI command handling.

## Project Help Flow

The `/project-rag build` command loads documentation files from the configured project path, chunks them, embeds each chunk through Ollama, and writes a SQLite index.

The `/help <question>` command embeds the question, retrieves the most relevant documentation chunks, asks the project context adapter for the current git branch, and sends the question plus retrieved context to the active LLM provider.

Project assistant slash-command behavior is shared through `ProjectAssistantCommandService`. The CLI prints command results, while the PyQt worker renders the same results as assistant messages. This keeps RAG and project context behavior out of UI-specific code.

The PyQt `Собрать RAG` button sends the same `/project-rag build` command path used by typed messages, so index-building behavior stays centralized.
