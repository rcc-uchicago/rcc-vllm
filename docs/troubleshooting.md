# Troubleshooting

This page collects the known failure modes of the ai-session service and their
fixes. Each section below is named after the error message or symptom you will
actually see, so searching this site for the error text lands here. Launch and
configuration instructions live on the client pages
([aider](coding/aider.md), [Continue](coding/continue.md),
[opencode and Cline](coding/opencode.md), [Claude Code](coding/claude-code.md),
[browser chat](getting-started.md));
this page assumes you followed one of them and something did not work.

## First checks

Before reading any symptom section, run this three-step diagnostic sequence. These
commands only inspect the session; they hold no GPU and change nothing. Run all three **on the login node** where you
started the session.

| Step | Description | Command |
|---|---|---|
| 1 | Is the session starting, ready, failed, or stopped? | `ai-session status` |
| 2 | Confirm the gateway process is alive and knows its backend | `curl -sf http://127.0.0.1:<GW_PORT>/__gateway/health` |
| 3 | Confirm the model server answers through the session URL | `eval "$(ai-session env)" && curl -s "$AISESSION_BASE_URL/models" -H "Authorization: Bearer $AISESSION_API_KEY"` |

- Replace `<GW_PORT>` with your port. The per-user default is
  `8400 + UID % 90`; print yours with `echo $((8400 + $(id -u) % 90))`.

Step 1 answers the usual question directly. It prints `session: READY -- open the
tunnel now.` (with the tunnel command for a chat session, or `client settings:
ai-session connect` for a coding session); `session: STARTING -- <stage> (m:ss
elapsed).` followed by `NOT ready yet: do not open the tunnel.`; `session: FAILED
-- <reason>.` with the path of the server log; or that no session is running. It
also shows whether an access key is set.

Step 2 checks the gateway — the small always-on connection point the service
runs on the login node. It gives clients one stable web address while the GPU
session behind it changes. Expected output:

```
{"gateway":"ok","backend_active":true}
```

This endpoint is reachable without the access key, so it reports only liveness and
whether a backend is published — never the backend's internal address (which must
not leak to other users on the login node).

If this curl fails, the gateway process is gone: see
[Connection refused after working for a while](#connection-refused-after-working-for-a-while).
If it succeeds but `backend_active` is `false`, the gateway is up but no session
has published a backend; requests will return an error of type `no_backend`. In
that case start a session from the owning page's recipe
([coding](coding/overview.md) or [browser chat](getting-started.md)).

Step 3 exercises the full path to the GPU. Expected output is an OpenAI-style
model list naming the model you started:

```
{"object":"list","data":[{"id":"qwen3.8_27B", ...}]}
```

## `Unknown context window size`

**Symptom.** aider (via litellm) warns:

```
Unknown context window size
```

**Cause.** litellm was not given the metadata file that declares the served
model's context window (32768 tokens) and zero per-token cost, so it cannot size
prompts. The `aider` provided by `module load ai-session` sets this file itself
(through `AIDER_MODEL_METADATA_FILE`) on every start, so the warning means a
different aider ran: your own install, earlier on your `PATH`, started without the
session's settings.

**Check.** `which aider` should print the path inside the ai-session module.

**Fix.** Run `module load ai-session` and then plain `aider`. To use your own aider
install, run `eval "$(ai-session env)"` in that shell first; it exports the
`AIDER_*` settings, including the metadata file. Details are on the
[aider page](coding/aider.md).

## Prompt reported as too long

**Symptom.** aider reports the prompt as too long, or refuses to send a request.

**Cause.** The metadata file splits the 32768-token context into a 28000-token
input budget and 4096 output tokens, so that prompt plus generated tokens can
never exceed the served context. Added file content has exceeded the 28000-token
input budget.

**Check.** Inside aider, run `/tokens` to see current context usage.

**Fix.** Remove files you are not editing with `/drop <path>`, or reset the
conversation history with `/clear` (added files remain). aider maintains a
repository map, so the model retains structural awareness of files you drop;
`/add` only the files you intend to edit.

## aider rejects a diff edit

**Symptom.** aider reports that it could not apply an edit the model proposed.

**Cause.** The model produced a malformed unified diff. This happens
occasionally; the default `--edit-format diff` is token-efficient but depends on
the model emitting a well-formed diff for that particular file.

**Fix.** First simply retry the request. If the same file fails repeatedly,
switch aider to whole-file rewrites — this is a client-side flag, so you do not
need to restart the GPU session. Exit aider and start it again with the flag,
which overrides the session's default of `diff`:

```bash
aider --edit-format whole
```

## Tool calls fail silently in opencode or Cline

**Symptom.** The agent reports that the model responded, but no file changed and
no command ran; the tool-call JSON appears as plain text in the model's reply.
No error is raised on either end.

**Cause 1: the session was started without `--agent`.** Tool calling is off by default, so
a session started for aider or Continue accepts no tool calls. Stop it and start it again:

```bash
ai-session stop
ai-session code --agent
```

**Cause 2: a leftover `AGENTS.md` workaround file.** If your repository root has an
`AGENTS.md` telling the model to spell out `<tool_call>` tags character by character —
required by earlier versions of these instructions — delete it. Every served model emits
tool calls natively, and the launcher selects the parser that matches the model, so that
file now asks for a format that is not the model's own. `AGENTS.md` is fine for ordinary
project instructions; it is only the tool-call workaround that has to go.

If tool calls still misbehave with `--agent` set and no workaround file present, use
[aider](coding/aider.md), which performs the same edits through chat completions
and text diffs without function calling, against the same endpoint.

## aider says no LLM model was specified, or asks about OpenRouter

**Symptom.** Running `aider` prints a message that no model is set, offers to log in
to OpenRouter, or prints:

```
No ai-session is running, so aider has no model to talk to. Start one first:
```

**Cause.** Either no session is running (or it is still starting), so there is no
model and access key to load, or an older or separate aider ran that does not load
the session's settings.

**Check.** `ai-session status` **on the login node**, and `which aider`.

**Fix.** If no session is running, start one with `ai-session code` (or
`ai-session code --cpu` to try things out) and wait for the READY box; then run
`aider` again. If a session is READY, run `module load ai-session` so that its
`aider` comes first on your `PATH`, or run `eval "$(ai-session env)"` before your
own aider. Decline the OpenRouter offer; it is not needed.

## opencode uses the wrong model

**Symptom.** opencode shows a model other than the session's (for example one
pinned by a repository's own `opencode.json`), or its requests are refused.

**Cause.** opencode read its settings from somewhere other than the running
session: a repository `opencode.json`, or `OPENCODE_CONFIG_CONTENT` left over from
an earlier session in that shell. `eval "$(ai-session env)"` sets an inline
configuration that takes precedence over a repository `opencode.json`, but only in
the shell where it was run and only for the session that was up at the time.

**Fix.** In the shell where you run opencode, re-run the eval after the session is
READY, then start opencode again:

```bash
eval "$(ai-session env)"
opencode
```

opencode then shows the model by its key (for example `qwen3.8_27B`). Re-run the
eval after every new session, since each session has a new access key.

## Claude Code says `Not logged in`

**Symptom.** `ai-session claude` starts, but Claude Code reports `Not logged in`,
or its requests fail with an authentication error.

**Cause.** The session it was pointed at has stopped or been restarted, so the
access key it was given is no longer valid; or no session was running and the key
is missing. `ai-session claude` passes the key of the session that was running when
you launched it, and `ai-session stop` deletes that key.

**Check.** `ai-session status` **on the login node**: it should report `READY` and
`access key: set`.

**Fix.** Exit Claude Code, wait for the session to be READY (start one with
`ai-session code --agent` if none is running), and run `ai-session claude` again.
Do not run `/login` inside this Claude Code: `ai-session claude` uses its own
configuration directory (`~/.ai-session/claude`) and the session key, not your
Anthropic login. See [Claude Code](coding/claude-code.md).

## opencode or Claude Code is slow on a `--cpu` session

**Symptom.** On a `--cpu` session, opencode or Claude Code takes tens of seconds to
minutes per reply, or the model does not use tools.

**Cause.** The time goes into reading the prompt. A CPU node reads prompt tokens
slowly, and these clients send large prompts, mostly tool definitions. On a CPU
session both run with their tools turned off for this reason. Measured on `amd`
(16 cores): opencode's prompt drops from 15,122 to 2,006 tokens and a reply from
about 2.5 minutes to 4 seconds; Claude Code's prompt drops from 15,000 to 24,000
tokens to 5,859, and a reply from 229 to 32 seconds. The 0.5B model served on CPU
cannot use tools reliably in any case.

**Fix.** Use the CPU session only to try the service and check client wiring. For
real coding work, start a GPU session:

```bash
ai-session stop
ai-session code --agent
```

## `model '...' is not fully staged`

**Symptom.** The start command exits immediately with:

```
ERROR: model 'qwen3.8_27B' is not fully staged at: <path>
       (missing config.json/*.safetensors, or a download is still in flight).
```

**Cause.** The model weights are not completely on disk in the service's model
store. The service refuses to reserve GPUs for a model whose directory lacks
`config.json` or `*.safetensors` files, or still contains `*.incomplete` shards
from an in-flight download.

**Fix.** Wait for staging to finish (RCC staff stage new models) and start
again, or start a model that is already staged, for example:

```bash
ai-session code --model qwen2.5_72B
```

!!! warning "The 72B reserves four GPUs, twice the coding default"
    Stop it with `ai-session stop` when finished.

## Port already in use at start

**Symptom.** The start command exits with:

```
Something is already listening on :<GW_PORT> (maybe a browser demo or another user).
```

**Cause.** The port defaults to `8400 + UID % 90`, derived from your user
ID so two users on one login node normally do not collide. The check trips when
you already have a session up on this node (chat and coding sessions share the
same default port; run one at a time), or when another user overrode their port
onto yours.

**Check.** See what is listening and whether it is yours:

```bash
ss -ltnp | grep :<GW_PORT>
```

**Fix.** If the listener is your own leftover session, stop it first:

```bash
ai-session stop
```

Otherwise pick a free port explicitly:

```bash
GW_PORT=8490 ai-session code
```

!!! note "Set the same GW_PORT on every command"
    `status`, `connect`, and `stop` read `GW_PORT` too. If you overrode it at
    start, prefix them with the same `GW_PORT=8490` or they will inspect the
    wrong port.

## I opened the tunnel and the page does not load

**Symptom.** The browser shows a connection error or an empty page at
`http://localhost:<UI_PORT>`, or a laptop client cannot connect, shortly after you
started the session.

**Cause.** The tunnel was opened before the session was ready. Until the READY box
appears, nothing is listening on the UI port (Open WebUI starts only after the
model has loaded), so the tunnel has nothing to forward to.

**Check.** `ai-session status` **on the login node**. `STARTING` means it is not
ready yet.

**Fix.** Wait until `ai-session status` reports `session: READY -- open the tunnel
now.` (or the READY box appears in the starting terminal), then reload the page.
A tunnel opened earlier usually works once the session is ready; if not, kill it
(`pkill -f "ssh -N -f -L <UI_PORT>"`) and run the tunnel command again. If the
session is READY and the page still does not load, see the next section.

## The client on your laptop cannot connect

**Symptom.** A client on your laptop (aider, Continue, a browser) cannot reach
`http://localhost:<GW_PORT>` although the [first checks](#first-checks) pass on
the login node.

**Cause.** The session's web address is served on `127.0.0.1` on the specific
login node where you started the session; it is not reachable from outside that
node. Your laptop reaches it only through an SSH tunnel, and the tunnel must
target that same login node. The usual causes are a tunnel that is not running,
or a tunnel opened to a different login node than the one hosting your session.

??? question "What is an SSH tunnel?"
    An SSH tunnel (`ssh -L`) forwards a port on your laptop to a port on a
    remote machine over the SSH connection. After
    `ssh -N -L 8412:localhost:8412 ...`, a client on your laptop that connects
    to `localhost:8412` is transparently connected to port 8412 on the login
    node. `-N` means the connection carries only the forward, no remote shell.

**Check.** With the tunnel supposedly open, run **on your laptop**:

```bash
curl -sf http://localhost:<GW_PORT>/__gateway/health
```

**Fix.** Re-run the tunnel command printed in the `READY` block at start — it
names the correct login node. Its form is:

```bash
ssh -N -L <GW_PORT>:localhost:<GW_PORT> <cnetid>@<login-node>.rcc.uchicago.edu
```

- Replace `<GW_PORT>` with your port (both occurrences).
- Replace `<cnetid>` with your CNetID.
- Replace `<login-node>` with the login node named in the `READY` block — not an
  arbitrary login node.

Leave the tunnel running for as long as you work, then point the laptop client
at `http://localhost:<GW_PORT>/v1`.

## Connection refused after working for a while

**Symptom.** The client worked, then requests start failing with connection
refused; `curl -sf http://127.0.0.1:<GW_PORT>/__gateway/health` on the login node
fails.

**Cause.** The gateway runs as a background process on the login node, started
from the terminal where you started the session. When the SSH connection hosting it
closed (laptop sleep, network drop), it died with that connection. The GPU session
may still be running, and still holding its GPUs.

**Check.** `ai-session status` **on the login node**. A server still listed
under `server:` means the GPU session survived the gateway.

**Fix.** Tear down cleanly, then start again, this time inside `tmux` or
`screen` so an SSH drop cannot kill the gateway. `ai-session stop` is safe to run
even when parts of the stack are already gone: it meters and ends any remaining
session, stops any remaining gateway, and prints the tokens consumed.

```bash
ai-session stop
ai-session code
```

## The terminal seems stuck after `submitted jobid`

**Symptom.** The start command prints `[start] submitted <model> jobid=<id>
port=<port>`, then a "vLLM is starting -- PLEASE WAIT" banner, and appears to hang.

**Cause.** This is normal: the model is loading. The command blocks until the
model has loaded and answered a probe, and prints a progress line with the elapsed
time whenever the stage changes (and periodically while it stays the same), for
example `[1:40] compiling and warming up the model ...`. The stages are: waiting
for a compute node; loading the model weights; compiling and warming up the model;
starting the API server; finishing start-up. Loading a coding model typically
takes several minutes after the node is assigned. While the stage is `waiting for
a compute node`, the cluster is busy and no node has been assigned yet; the
session holds nothing during that wait.

**Check.** In a second terminal **on the login node**:

```bash
ai-session status
```

`STARTING` with the current stage means it is still loading: wait for `READY`.
`FAILED` gives the reason and the server log path. For more detail, follow the
launch log under your state directory (`run/start.log`).

**Fix.** Wait. If the model server stops while loading, start-up now ends at once
with the log path rather than waiting out the timeout; see the log, and the
symptom sections above. The start command gives up after `READY_TIMEOUT` seconds
(900 for a coding session; chosen per model for browser chat). If the load is
slow but progressing and will not finish in time, cancel with `Ctrl-C`, run
`ai-session stop`, and restart with a longer timeout, for example
`READY_TIMEOUT=1800 ai-session code`.

## Getting help

For anything not covered here, use the support channels listed on the
[front page](index.md). When reporting a problem, include the session id shown
by `ai-session status` (or the job id on the receipt printed at stop). For a
usage question, also include the receipt path printed by `ai-session receipt`.
