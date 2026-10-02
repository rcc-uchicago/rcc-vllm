# opencode and Cline (Tool-Calling Agents)

opencode and Cline are autonomous coding agents. They differ from [aider](aider.md)
in how they drive the model: instead of asking for edits as plain text, they use
native function calling (tool calling), where the model returns a
structured call — a function name plus JSON arguments — that the agent then executes
(read a file, apply an edit, run a command (grep), run a tool (squeue)). opencode is a
supported client; it needs no configuration file — one `eval` line loads the session's
settings (Step 2) — and occasionally a retry. aider remains the default and recommended
client: it performs the same edits through the chat-completions API without function
calling.

Because these agents need function calling, the session must be started with tool
calling enabled (`ai-session code --agent`); a session started for aider or
[Continue](continue.md) will not accept tool calls. For how sessions, the gateway
(the connection point on the login node), and SSH tunnels fit together, see
[Coding Sessions](overview.md).

## Quick Start

| Step | Description | Command | Run on |
|---|---|---|---|
| 1 | Start a session with tool calling enabled; wait for the READY box | `ai-session code --agent` | Login node |
| 2 | Put opencode on your PATH | `module load opencode` | Login node |
| 3 | Load the session's settings into the shell | `eval "$(ai-session env)"` | Login node |
| 4 | Run opencode inside your git repository | `opencode` | Login node |
| 5 | Stop the session when finished | `ai-session stop` | Login node |

## Step 1: Start the session with tool calling enabled

Run this **on the login node**, inside `tmux` or `screen` so an SSH disconnect does
not terminate the gateway:

```bash
ai-session code --agent
```

!!! warning "A running session holds its node whether or not you send requests"
    The session occupies its GPUs (2 A100 for the default Qwen3.8-27B) until you
    stop it, busy or idle. Stop with `ai-session stop` as soon as you finish.

`--agent` starts the model server with tool calling enabled, selecting the tool-call
parser that matches the model you are serving. This switch controls only tool calling; the
served context length is independent of it and stays at the coding default of 32768 tokens.

The command shows start-up progress and blocks until the model is loaded
(typically several minutes for the 27B model), then prints the READY box. Do not
start opencode before the READY box appears. From another terminal, check at any
time:

```bash
ai-session status
```

It reports `session: STARTING -- <stage>` while loading and `session: READY` once
clients can connect.

## Step 2: Run opencode

On the cluster, opencode is a central module, the same as `ai-session` itself:
`module load opencode` works from any login node with no `module use` line and no
special group membership. **On the login node**, in your git repository:

```bash
module load opencode
cd /path/to/your/repo
eval "$(ai-session env)"
opencode
```

`eval "$(ai-session env)"` exports the session URL, access key, and model name, and
`OPENCODE_CONFIG_CONTENT`, an inline opencode configuration built from those values.
No `opencode.json` is needed, nothing in your repository or your personal
`~/.config/opencode/` is modified, and the same line works unchanged for every
session, port, and key. Run the `eval` line again after starting a new session: the
access key changes with every session. The line also sets `OPENAI_API_KEY` in that
shell to the session key, replacing any value you had there.

What the inline configuration does: it routes requests through the generic
OpenAI-compatible adapter (`@ai-sdk/openai-compatible`) to the session URL with the
session access key; `model` and `small_model` both point at the session's model, so
no request leaves the cluster (opencode's default `small_model`, used for session
titles, is an externally hosted model); `enabled_providers` makes the local provider
the only selectable one; `share` is disabled and `autoupdate` is off, so the tool
does not contact opencode's external services while you work; a `limit` block
declares the served 32768-token context and an 8192-token output cap so opencode
sizes its prompts correctly. opencode shows the model under its served name, for
example `qwen3.8_27B`.

The inline configuration takes precedence over a repository's own `opencode.json`,
so a project file that pins some other model does not redirect your requests.

Verification, before spending tokens:

```bash
opencode models   # lists one model: rcc/<the model your session serves>
```

!!! note "A per-repository file is still possible"
    `$AISESSION_HOME/ai-session/opencode.example.json` still ships with the service
    for anyone who prefers an `opencode.json` checked into a repository. It reads the
    URL and key from the same environment variables, so you still run
    `eval "$(ai-session env)"` first; its model name is fixed to `qwen3.8_27B` and
    must be edited if you serve another model.

!!! note "Personal MCP servers inflate every prompt"
    MCP servers declared in your personal `~/.config/opencode/opencode.json` are
    advertised to the model as extra tools on every request. If you have any, disable
    them for ai-session work (set `"enabled": false` on each entry).

### opencode on your laptop

Install opencode there with the official script,
`curl -fsSL https://opencode.ai/install | bash` (or `npm install -g opencode-ai`).
Open the SSH tunnel printed in the READY box so `localhost:<GW_PORT>` reaches the
session (see [Coding Sessions](overview.md#remote-access-from-your-laptop)), then
copy the settings that `ai-session connect` prints. On the cluster this step is
unnecessary: the module provides opencode and no tunnel is needed.

### opencode on a CPU session

On a CPU session (`ai-session code --cpu --agent`), `eval "$(ai-session env)"`
loads a variant of the inline configuration with opencode's tools turned off. The
tool definitions are most of opencode's prompt, and a CPU node reads prompts
slowly: measured, the prompt drops from 15,122 to 2,006 tokens and a reply from
about 2.5 minutes to 4 seconds. The 0.5B CPU model cannot use tools reliably
anyway. On a CPU session opencode can therefore answer questions but cannot read
or edit files; use it to try the service and check your setup, not for coding work.

### If you have an `AGENTS.md` workaround file, delete it

Earlier versions of these instructions required an `AGENTS.md` rules file in your repository
root that told the model to spell out `<tool_call>` tags character by character. **That file
is now counterproductive: delete it.** Every served model emits tool calls natively, and the
launcher selects the parser that matches the model — `qwen3_coder` for `qwen3.8_27B`, whose
calls come back in an XML form:

```
<tool_call>
<function=read_file>
<parameter=path>
/etc/hostname
</parameter>
</function>
</tool_call>
```

An `AGENTS.md` file that asks for a hand-written format instead tells the model to produce
something that is not its native output. `AGENTS.md` remains useful for ordinary project
instructions; it is only the tool-call workaround that must go.

### Run

If opencode occasionally prints tool-call JSON as ordinary chat text instead of acting on
it, re-issue the instruction. If it happens on every turn, check that the session was
started with `--agent` and that you have no leftover `AGENTS.md` workaround file; switch to
[aider](aider.md) if it persists. See also [Troubleshooting](../troubleshooting.md).

### Seeing the model's reasoning

The Qwen3-family models think before answering. Served with `--reasoning-parser qwen3`,
their chain of thought comes back in a separate `reasoning_content` field, kept
out of the answer (see [Command Reference](../reference.md)). opencode reads that
field and displays it as a **Thinking** block, but the display is off by default.

To use it, start a thinking session and point opencode at that model:

```bash
ai-session code --model qwen3_4b --agent           # serve a thinking model
eval "$(ai-session env)"                           # opencode now uses rcc/qwen3_4b
opencode run --thinking "…"                        # prints a "Thinking: …" block, then the answer
```

The interactive TUI shows the thinking block inline above each reply. `qwen3_4b` and the
coding default `qwen3.8_27B` reason this way by default. `gemma4_31B` can, but only when you
ask for it per request; the Qwen2.5 models do not think at all, so `--thinking` has no
effect with them. aider, by contrast, does not surface `reasoning_content` against this
endpoint — it shows only the answer.

## Cline

Cline is a VS Code extension in the same class of tool: an autonomous agent driven
by native tool calling. Configure it with the same three values — base URL
`http://localhost:<GW_PORT>/v1`, API key the session access key, model
`qwen3.8_27B` — against a session started with `ai-session code --agent`.
Cline has not been **tested** against this service; nothing is known to be wrong with it,
but nothing has been verified either. aider is the fallback.

## Step 3: Stop the session

!!! warning "Stop the session as soon as you stop working"
    A session holds its node until it is stopped, regardless of request volume.
    Run `ai-session stop` immediately when you finish:

```bash
ai-session stop
```

This releases the GPUs, stops the gateway, deletes the access key, and prints a
TOKEN USAGE box: the model, where it ran, tokens in, out, and total, the number of
requests, the job id, and the receipt file path.
