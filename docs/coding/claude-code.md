# Claude Code

`ai-session claude` runs Claude Code, Anthropic's terminal coding agent, against the
model your ai-session is serving instead of against Anthropic's servers. The model
server (vLLM) also speaks the Anthropic Messages API (`/v1/messages`), and the
gateway — the connection point on the login node — passes those requests through
with the same access-key check and token logging as every other client. No prompt,
file content, or completion leaves the cluster.

Claude Code is a tool-calling agent, like [opencode](opencode.md): it reads files,
edits them, and runs commands on your behalf. Read
[Agent responsibilities and risks](agents.md) before using it on real work.

## Requirements

- Claude Code installed, so that `claude` is on your PATH on the login node. It is
  not part of the service. Install it with:

    ```bash
    curl -fsSL https://claude.ai/install.sh | bash
    ```

- A running ai-session coding session started with `--agent` (tool calling).
- No Anthropic account is needed for `ai-session claude`.

## Steps

1. Start a session **on the login node**, inside `tmux` or `screen`. For real use,
   start a GPU coding session (Qwen3.8-27B by default):

    ```bash
    ai-session code --agent
    ```

    To try the setup without holding a GPU, start a CPU session instead (see
    [Running on a CPU session](#running-on-a-cpu-session)):

    ```bash
    ai-session code --cpu --agent
    ```

    Add `--account <acct> --partition <part>` the first time (for `--cpu`, a CPU
    partition such as `amd` or `caslake`).

2. Wait for the READY box in the start terminal. From another terminal,
   `ai-session status` reports `session: STARTING -- <stage>` while the model loads
   and `session: READY` once clients can connect.

3. In a second terminal, change into the git repository you want to work in and
   run:

    ```bash
    cd /path/to/your/repo
    ai-session claude
    ```

    No `eval "$(ai-session env)"` is needed; the command reads the session's
    settings itself. The first interactive run shows Claude Code's one-time setup
    screens. Extra arguments are passed to `claude`, for example a single
    non-interactive question:

    ```bash
    ai-session claude -p "summarize what utils.py does"
    ```

4. Check the model. In Claude Code, type `/model`: the only entry is
   `<model> (ai-session)`, for example `qwen3.8_27B (ai-session)`, and the same name
   appears in the status line. If you see an Anthropic model name instead, you
   started plain `claude`, not `ai-session claude`.

5. When you are finished, leave Claude Code and stop the session **on the login
   node**:

    ```bash
    ai-session stop
    ```

    This releases the node and prints the TOKEN USAGE box for the session, which
    includes Claude Code's requests.

## What `ai-session claude` sets, and why your normal `claude` is unaffected

Everything is scoped to that one run of Claude Code. Nothing is written to your
shell, your `~/.claude` directory, or your Claude Code settings files.

| Setting | Value | Purpose |
|---|---|---|
| `ANTHROPIC_BASE_URL` | `http://localhost:<GW_PORT>` (the gateway) | Sends requests to your session instead of to Anthropic. |
| `ANTHROPIC_AUTH_TOKEN` | the session access key | Authenticates to the gateway; a request without it is refused. |
| `ANTHROPIC_MODEL` | the session's model, e.g. `qwen3.8_27B` | Selects the served model. |
| `CLAUDE_CODE_MAX_OUTPUT_TOKENS` | `4096` | Keeps each reply inside the session's 32768-token context. |
| `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` | `1` | Turns off Claude Code's non-essential network traffic. |
| `--settings` (model picker) | one entry, `<model> (ai-session)` | Shows the session model under its own name in `/model` and the status line. |
| `CLAUDE_CONFIG_DIR` | `~/.ai-session/claude` | A separate configuration directory: your normal login, history, plugins, and hooks are neither used nor changed. |

Any `ANTHROPIC_API_KEY` in your environment is removed for that run. Because all
of this applies only to the process `ai-session claude` starts, a later plain
`claude` uses Anthropic with your own login, as usual.

## Running on a CPU session

On a CPU session (`--cpu`) the model is the 0.5-billion-parameter `qwen2.5_0.5B`,
and `ai-session claude` starts Claude Code with its tools turned off. Claude Code's
tool definitions are 15,000 to 24,000 tokens per request, which a CPU node takes
minutes to read, and a model of that size cannot use them reliably. Measured on the
`amd` partition (16 cores):

| | With tools | Without tools |
|---|---:|---:|
| Prompt size | 15,000–24,000 tokens | 5,859 tokens |
| Reply time | 229 s | 32 s |

Without tools Claude Code can answer questions but cannot read or edit files or
run commands. Use a CPU session to confirm that Claude Code connects; use a GPU
session for coding work.

## Limits

- Claude Code is built for much larger models. With a small model (`qwen2.5_0.5B`,
  and to a lesser degree `qwen3_4b`) it cannot drive its tools: expect tool calls
  that fail or are printed as text. Practical use needs a GPU coding session,
  `ai-session code --agent` with the default Qwen3.8-27B.
- Replies are capped at 4,096 output tokens.
- Claude Code may print notices that assume an Anthropic model or account. They
  are harmless and do not affect the session.

## Troubleshooting

| Message or symptom | Cause | Resolution |
|---|---|---|
| `Claude Code is not installed (no 'claude' on PATH)` | Claude Code is not installed, or not on PATH in this shell. | Install it: `curl -fsSL https://claude.ai/install.sh \| bash`, then open a new shell. |
| `No ai-session is running. Start one first ...` | No session is up, or it is still starting. | Start one with `ai-session code --agent` (or `ai-session code --cpu --agent`); wait until `ai-session status` reports `READY`. |
| `Not logged in` inside Claude Code | The session access key is missing: the session was stopped, or is being restarted, after Claude Code started. | Leave Claude Code, wait until `ai-session status` reports `READY`, and run `ai-session claude` again. |
| `/model` shows an Anthropic model | Plain `claude` was started. | Run `ai-session claude` instead. |
| Replies take minutes | A CPU session, or very large files in context. | Use a GPU session for real work. |
