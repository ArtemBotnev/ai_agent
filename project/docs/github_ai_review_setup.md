# GitHub AI Code Review Setup

This guide describes how to review pull requests in another GitHub repository with `ai_second`.

There are two repositories:

```text
ai_second
  The reviewer repository. It contains the agent, RAG, prompts, and review workflow.

target_repo
  The repository you want to review. It contains only a small workflow that calls ai_second.
```

`target_repo` is reviewed. `ai_second` is only the review tool.

## Result

When a pull request is opened or updated in `target_repo`, GitHub Actions sends a job to your self-hosted runner. The runner checks out both repositories, builds a temporary RAG index for `target_repo`, asks local Ollama for embeddings and review text, and publishes the review back to the pull request.

You will see the review in:

- the pull request conversation as a bot comment;
- the GitHub Actions job summary.

## Requirements

On the machine that will run the self-hosted runner:

```text
git
Python 3.12
Ollama
internet access to GitHub
```

A static IP address is not required. The runner opens an outgoing connection to GitHub and waits for jobs.

Install or pull the models used by the reviewer:

```bash
ollama pull nomic-embed-text
ollama pull llama3.1:8b
```

The chat model is configured in `ai_second/agent_config/llm.yaml`. The default provider is `ollama`.

## Step 1: Publish ai_second

Push `ai_second` to GitHub, for example:

```text
github.com/YOUR_USER/ai_second
```

This repository must contain:

```text
.github/workflows/ai-code-review.yml
scripts/review_pr.py
application/code_review/
application/project_help/
agent_config/project_assistant.example.yaml
```

If `ai_second` is private, make sure `target_repo` is allowed to call reusable workflows and checkout this repository.

## Step 2: Add Workflow To target_repo

In the repository you want to review, add:

```text
.github/workflows/ai-review.yml
```

The ready-to-copy example is stored in `project/examples/target_repo_ai_review.yml`. Use this content:

```yaml
name: AI Review

on:
  pull_request:
    types: [opened, synchronize, reopened]

permissions:
  contents: read
  pull-requests: write

jobs:
  ai-review:
    uses: ArtemBotnev/ai_agent/.github/workflows/ai-code-review.yml@task-32
    with:
      reviewer_repository: ArtemBotnev/ai_agent
      reviewer_ref: task-32
```

`uses` must be a full reference in the form `owner/repository/.github/workflows/file.yml@ref`.
For the current development branch this is `ArtemBotnev/ai_agent/.github/workflows/ai-code-review.yml@task-32`.
`reviewer_ref` must point to the same branch or tag that should be checked out as the reviewer code.
After merging to the main branch, replace `@task-32` and `reviewer_ref: task-32` with `@main` / `reviewer_ref: main` or `@master` / `reviewer_ref: master`.

Nothing else from `ai_second` needs to be copied into `target_repo`.

## Step 3: Create Self-Hosted Runner

Open `target_repo` on GitHub:

```text
Settings -> Actions -> Runners -> New self-hosted runner
```

Choose your OS and architecture. GitHub will show commands similar to these:

```bash
mkdir actions-runner
cd actions-runner
curl -o actions-runner-linux-x64.tar.gz -L https://github.com/actions/runner/releases/download/...
tar xzf ./actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/YOUR_USER/target_repo --token YOUR_TOKEN
```

Start the runner interactively:

```bash
./run.sh
```

When the runner is running, GitHub should show it as `Idle`.

For permanent background mode on Linux:

```bash
sudo ./svc.sh install
sudo ./svc.sh start
```

The local machine must be powered on and the runner must be online when PR review jobs should run.

## Step 4: Check Local Ollama

On the same machine as the runner:

```bash
ollama list
```

Make sure these models are present:

```text
nomic-embed-text
llama3.1:8b
```

The workflow also runs:

```bash
bash scripts/start_project_ollama.sh
```

from the checked out `ai_second` repository. That script starts Ollama if needed and pulls the configured embedding model.

## Step 5: Open A Pull Request

In `target_repo`:

1. create a branch;
2. change code;
3. push the branch;
4. open a pull request.

GitHub will run:

```text
AI Review
```

The reusable workflow from `ai_second` will:

1. checkout `target_repo` into `target-repo`;
2. checkout `ai_second` into `ai-reviewer`;
3. install Python dependencies from `ai_second/requirements.txt`;
4. start Ollama embeddings;
5. run `ai_second/scripts/review_pr.py` against `target_repo`;
6. write `pr_review.md`;
7. publish the review as a PR comment and job summary.

## What Runs On The Local Machine

The runner executes the job locally. During the job it creates a temporary RAG SQLite index:

```text
project_rag_index.sqlite
```

inside the runner workspace. This file is not committed and is not stored in GitHub.

The RAG index is built from `target_repo`, not from `ai_second`.

The review script uses:

```bash
git diff BASE_SHA...HEAD_SHA
```

inside `target_repo`, retrieves relevant text chunks with RAG, then calls the configured Ollama chat model.

## Where To Read The Review

Open the pull request in `target_repo`.

The review appears as a PR comment containing:

```markdown
## Potential Bugs
## Architecture Concerns
## Recommendations
```

The workflow uses this marker:

```text
<!-- ai-second-code-review -->
```

If the PR is updated, the workflow updates the existing AI review comment instead of creating a new one.

You can also open:

```text
Actions -> AI Review -> job summary
```

to read the same Markdown output.

## Local Debug Run

Local debug is optional. It is useful only if the GitHub workflow fails or you want to test prompt changes before opening a PR.

From the `ai_second` repository:

```bash
python scripts/review_pr.py \
  --project-path /path/to/target_repo \
  --base-ref origin/main \
  --head-ref HEAD \
  --index-file /tmp/target_review_rag.sqlite \
  --output /tmp/target_ai_review.md
```

Then read:

```bash
cat /tmp/target_ai_review.md
```

## Troubleshooting

If the GitHub job waits forever, check that the self-hosted runner is online:

```text
target_repo -> Settings -> Actions -> Runners
```

If the job cannot find Ollama, install Ollama on the runner machine and make sure `ollama` is available in `PATH`.

If model loading fails, pull the models manually:

```bash
ollama pull nomic-embed-text
ollama pull llama3.1:8b
```

If `ai_second` is private and checkout fails, configure repository access for reusable workflows or use a public reviewer repository.

If the review comment is not created, verify the workflow permissions:

```yaml
permissions:
  contents: read
  pull-requests: write
```
