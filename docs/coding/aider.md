# aider

aider is the default coding client for AI sessions. It drives the model through the
chat-completions API and applies edits as text — unified diffs or whole-file
replacements — so it does not depend on the model's function-calling support, which
is the least reliable part of serving a local model. Tool-calling agents such as
opencode and Cline are covered on [opencode and Cline](opencode.md); the shared
session lifecycle (`ai-session code`, `ai-session status`, `ai-session stop`) is
on [Coding Sessions](overview.md).

aider is already installed as part of the service; you do not install anything.
`module load ai-session` puts it on your PATH. It requires the working directory to
be inside a git repository — run `git init` first if necessary.

## Quick start

| Step | Description | Command | Run on |
|---|---|---|---|
| 1 | Start a coding session and wait for the READY box (procedure on [Coding Sessions](overview.md)) | `ai-session code` (or `ai-session code --cpu` to try it on a CPU node) | Login node |
| 2 | Change into the git repository you want to edit | `cd /path/to/your/repo` | Login node |
| 3 | Run aider | `aider` | Login node |
| 4 | Stop the session when finished | `ai-session stop` | Login node |

!!! warning "A running session holds its node whether or not you send requests"
    A session occupies its node (GPU or CPU) until you stop it, busy or idle. Stop
    it with `ai-session stop` as soon as you stop working.

## Step 1: Run aider

Run aider **on the login node** where you started the session, in a second
terminal (leave the start terminal running), after the start terminal shows the
READY box or `ai-session status` reports `session: READY`:

```bash
cd /path/to/your/repo
aider
```

There is no further configuration. Each time it starts, the `aider` command
provided by the service reads the running session's settings — the session URL,
the access key, the model name, the context-window metadata, and the edit
format — so they always match the session that is up now, and a key from an
earlier session cannot linger. You do not need `eval "$(ai-session env)"` for
aider, and you do not pass `--model`, `--model-metadata-file`, or
`--edit-format`.

If no session is running, aider does not start; it prints:

```
No ai-session is running, so aider has no model to talk to. Start one first:

  ai-session code            (GPU)
  ai-session code --cpu      (CPU-only, small model; for trying things out)

then run `aider` again. `ai-session status` shows whether it is ready.
```

What the service sets for you, and why:

| Setting | Value | Purpose |
|---|---|---|
| `OPENAI_API_BASE`, `OPENAI_API_KEY` | session URL (`http://localhost:<GW_PORT>/v1`) and access key | Read by litellm, the client library aider uses to send requests in the standard OpenAI API format. Every request must carry the key; a request without it is refused with HTTP 401. |
| `AIDER_MODEL` | `openai/<model>` | Selects the served model. The `openai/` prefix selects the standard format in litellm. |
| `AIDER_WEAK_MODEL` | `openai/<model>` | Routes aider's auxiliary requests (commit messages, history summarization) to the same local model rather than to `api.openai.com`. |
| `AIDER_MODEL_METADATA_FILE` | the service's `aider_model_metadata.json` | Declares the model's context window (32768 tokens) and zero token cost to litellm. Without it, litellm cannot size prompts and prints `Unknown context window size`. |
| `AIDER_EDIT_FORMAT` | `diff` | Requests unified-diff edits instead of full-file rewrites. |
| `AIDER_ANALYTICS_DISABLE` | `true` | Disables aider's own usage telemetry. This is a client-side concern separate from the model traffic, which never leaves RCC; the [Data location note on the home page](../index.md#data-location) covers the distinction. |

Options given on the command line still take precedence over these settings. For
example, if diffs are rejected for a given file, run `aider --edit-format whole`.

The metadata file splits the 32768-token window as 28000 input tokens and 4096
output tokens, so prompt plus generated tokens cannot exceed the window.

To run aider on your laptop instead, open the SSH tunnel printed in the READY box
(see [Coding Sessions](overview.md#remote-access-from-your-laptop)) and give your
own aider installation the values `ai-session connect` prints.

Verification: aider starts its interactive prompt without printing
`Unknown context window size`. At the prompt, type `/tokens`; it reports current
context token usage against the window.

!!! note "aider on a CPU session"
    A CPU session (`ai-session code --cpu`) serves the 0.5B model
    `qwen2.5_0.5B`. aider connects to it the same way, which is useful for checking
    that your setup works, but a model of that size produces poor edits. Use a GPU
    session for real work.

## In-session commands

| Command | Effect |
|---|---|
| `/add <path>` | Add a file to the editable context. |
| `/drop <path>` | Remove a file from the context. |
| `/ask <question>` | Ask a question without editing files. |
| `/tokens` | Report current context token usage. |
| `/clear` | Clear conversation history; added files remain. |
| `/run <cmd>` | Run a shell command and optionally add its output to the context. |

aider maintains a repository map, so the model has structural awareness of files you
have not explicitly added; add files with `/add` only when you intend to edit them.

## Non-interactive use

To make a single edit and exit, for example from a batch script, add `--yes-always`
(answers aider's confirmation prompts), `--no-auto-commit` (leaves the change
uncommitted for review), and `--message`:

```bash
aider --yes-always --no-auto-commit \
  --message "add type hints to the public functions in utils.py"
```

Verification: `git diff` in the repository shows the edit; nothing was committed.

Standard input can be piped in, for example to analyze a log file:

```bash
cat build.log | aider --message "explain the traceback in this log and propose a fix"
```

## Errors

aider-specific error messages — `Unknown context window size`, the prompt reported
as too long, and rejected diff edits — are listed with resolutions on
[Troubleshooting](../troubleshooting.md).
