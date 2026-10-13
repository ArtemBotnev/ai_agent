# Architecture

The project follows a layered structure.

`domain` stores pure data models and domain rules. It does not own persistence or provider-specific LLM behavior.

`application` coordinates use cases. Chat orchestration lives in `application/chat`, memory use cases live in `application/memory`, summarization lives in `application/summary`, project documentation help lives in `application/project_help`, and pull request review lives in `application/code_review`.

`infrastructure` contains adapters for storage and external project context. JSON repositories persist chat history, memory, facts, summaries, and branches. Markdown repositories persist user profile and invariants.

`config` loads YAML configuration and converts it into typed dataclasses used by the runtime.

`main.py` wires the dependencies together and owns CLI command handling.

## Project Help Flow

The `/project-rag build` command loads configured text source files from the project path, chunks them, embeds each chunk through Ollama, and writes a SQLite index.

The `/help <question>` command embeds the question, retrieves the most relevant documentation chunks, asks the project context adapter for the current git branch, and sends the question plus retrieved context to the active LLM provider.

Project assistant slash-command behavior is shared through `ProjectAssistantCommandService`. The CLI prints command results, while the PyQt worker renders the same results as assistant messages. This keeps RAG and project context behavior out of UI-specific code.

The PyQt `Собрать RAG` button sends the same `/project-rag build` command path used by typed messages, so index-building behavior stays centralized.

## Code Review Flow

Pull request review is intentionally separated from GitHub. `scripts/review_pr.py` receives a target repository path and base/head refs, then `application/code_review.diff_loader` reads the unified diff, changed file statuses, and text snapshots of changed files.

`CodeReviewService` reuses the project assistant configuration, embeddings, RAG index, and project context adapter. It retrieves project documentation/source chunks relevant to the diff and prepares a single-use LLM request. The request is executed through `ChatService.answer_once`, so review runs do not modify normal chat history.

The GitHub workflow is a thin automation layer. It reacts to `pull_request`, checks out the target repository and the reviewer repository, runs the local review script on a self-hosted runner with Ollama, and publishes the Markdown review back to the PR.
