# Getting Started: Browser Chat

This page takes you from a login-node shell to chatting with an on-cluster model in
your browser, and it is the complete guide to the browser (Open WebUI) client. Three
pieces are involved: a **model server** (running on a GPU node inside the cluster,
speaking the standard OpenAI API format that most AI tools can talk to), a
**gateway** (a small always-on relay the service runs on the login node
at a fixed per-user port, so the session URL never changes between sessions and every
request's token counts are recorded), and **Open WebUI** (the chat
interface, also on the login node). One command, `ai-session chat`, starts all
three; `ai-session stop` stops them.

Only the model server holds cluster resources: it occupies its node (GPUs, or a
CPU node for a `--cpu` session) from the moment it starts until you run
`ai-session stop`, whether or not you send requests. Usage is reported to you as
the tokens the session consumed, printed when you stop it. Service Units are still
recorded for RCC staff but are not shown; the policy is on
[Billing and Service Units](billing.md).

For coding tools (aider, Continue, opencode, Claude Code) against the same service,
see [Coding Sessions](coding/overview.md) instead; this page covers browser chat
only. In brief: start `ai-session code`, then run plain `aider`
([aider](coding/aider.md)), or `eval "$(ai-session env)"` followed by `opencode`
([opencode](coding/opencode.md)), or `ai-session claude`
([Claude Code](coding/claude-code.md)). No client configuration file is needed.

## Quick start

| Step | Description | Command | Run on |
|---|---|---|---|
| [0](#step-0-load-the-module) | Put `ai-session` on your PATH | `module load ai-session` | Login node |
| [1](#step-1-start-the-session) | Start the session and the chat UI (first run: add `--account <acct> --partition <part>`); wait for the READY box | `ai-session chat` | Login node |
| [2](#step-2-open-the-ssh-tunnel) | Only after READY: forward the UI port to your machine | `ssh -N -f -L <UI_PORT>:localhost:<UI_PORT> <user>@<login-node>.rcc.uchicago.edu` | Local machine |
| [3](#step-3-chat-in-the-browser) | Chat | Browse `http://localhost:<UI_PORT>` | Local machine |
| [4](#step-4-check-status) | Check whether the session is starting, ready, or stopped | `ai-session status` | Login node |
| [5](#step-5-stop-and-read-the-token-usage) | Stop everything and print the tokens consumed | `ai-session stop` | Login node |

## Prerequisites

- **An RCC account.** No special group membership is required.  Get an [RCC Account here](https://rcc.uchicago.edu/accounts-allocations/request-account) .
- A **Slurm account and GPU partition** to run the GPU job under (or a CPU
  partition for a [CPU-only trial](#trying-the-service-without-a-gpu)). These are unique
  to you and your PI: the first time you start a
  session you pass them with `--account` and `--partition`, and they are then
  remembered (see [Step 1](#step-1-start-the-session)). 
- Run the login-node commands inside `tmux` or `screen`, so that an SSH disconnect
  does not kill the relay and UI processes that the start command leaves running.
  
Your writable state (chat history, session files, usage logs) is kept separate
under a per-user directory. Ports are likewise derived from your numeric user ID.

## Step 0: load the module

Once per shell, **on the login node**:

```bash
module load ai-session
```

This puts the `ai-session` command on your PATH.

## Step 1: start the session

The first time you start any session, name your Slurm account and GPU partition
**on the login node**, inside `tmux` or `screen`:

```bash
ai-session chat --account <your-account> --partition <your-partition>
```

The two values are saved to `~/.ai-session/config`, so from then on
`ai-session chat` (or `code`, or `fast`) needs no flags; pass `--account` or
`--partition` again only to change them. Without a saved account and partition,
the command stops before reserving any GPU and tells you what to set.

!!! warning "A running session holds its node whether or not you send requests"
    From the moment the job starts, the `chat` preset holds four A100 GPUs until you
    run `ai-session stop` (or the `--time` limit ends it). Always stop the session
    when you finish. For casual use, `ai-session fast` serves a small model on one
    GPU.

`ai-session chat` does four things, in order:

1. Starts the model server on cluster GPUs and blocks until the model actually
   answers. Loading takes a few minutes; the command prints its progress (see
   [What you see while it starts](#what-you-see-while-it-starts)).
2. Starts the gateway on `127.0.0.1:<GW_PORT>` and waits for its health check
   address to return HTTP 200.
3. Starts Open WebUI on `127.0.0.1:<UI_PORT>` (its Python imports are heavy;
   expect roughly 30 to 60 seconds).
4. Prints the SSH tunnel command for the login node it ran on, the URL to browse,
   and the session access key.

Options and their defaults:

| Option | Default | Meaning |
|---|---|---|
| `--account NAME` | none — required once | Your Slurm account. Required on the first run, then remembered in `~/.ai-session/config`. |
| `--partition NAME` | none — required once | The GPU partition to run in. Required on the first run, then remembered. |
| `--time HH:MM:SS` | `02:00:00` | Session time limit. The session ends after this even if you forget `ai-session stop`, which caps how long it can hold its node. |
| `--model KEY` | preset's model | Serve a different registered model (e.g. `qwen3.8_27B` or `gemma4_31B` for coding, `qwen3_4b` for the cheapest option); the right GPU configuration is chosen for you. See [Command Reference](reference.md#models). |
| `--agent` | off | Enable native tool calling, so a tool-calling model can call the opt-in [reference tools](#web-search-and-reference-tools-opt-in) itself. Not needed for web search or URL fetch. |
| `--lora NAME=PATH` | none | Also serve your own fine-tuned adapter; see [Your Own Fine-Tuned Model](lora.md). Repeatable. Not available with `--cpu`. |
| `--cpu` | off | Run on a CPU-only partition with the small Qwen2.5 0.5B model; see [Trying the service without a GPU](#trying-the-service-without-a-gpu). |

The presets:

| Command | Model | Resources held |
|---|---|---|
| `ai-session chat` | Qwen2.5 72B Instruct | 4 x A100-80GB |
| `ai-session fast` | Qwen3 4B | 1 x A100 |
| `ai-session chat --cpu` | Qwen2.5 0.5B Instruct | one CPU node, no GPU |

At start the command prints "usage is reported as the tokens this session consumes
(shown when you stop it)." There is no cost estimate before the job is submitted.

### What you see while it starts

Right after the job is submitted, the terminal prints a banner:

```
==================================================================
  vLLM is starting -- PLEASE WAIT. The web page is NOT ready yet.
  Do not open the SSH tunnel or the browser until you see the
  READY box with the tunnel command. Progress is shown below;
  from another terminal, `ai-session status` shows it too.
==================================================================
```

The command is not stuck: it is waiting for the model. Progress lines follow, each
with the elapsed time, for example `[1:40] compiling and warming up the model ...`.
The stages, in order, are: waiting for a compute node; loading the model weights;
compiling and warming up the model; starting the API server; finishing start-up.
Once the model is loaded, Open WebUI still has to start, and the terminal says
"The model is loaded, but the web page is still NOT ready -- please wait for the
READY box." If the model server stops while loading, start-up ends at once and
prints the path of the server log; see [Troubleshooting](troubleshooting.md).

Verification: the command ends with a READY block (your port, user, login node,
and model filled in). Do not open the tunnel before it appears. If it does not
appear, see [Troubleshooting](troubleshooting.md).

```
================ READY -- chat in your browser ================

  SESSION ACCESS KEY:  <32-hex-character key>

  The gateway now REQUIRES this key. The Open WebUI started here already uses it,
  so YOUR browser tab works out of the box. ...

On your LAPTOP, open the tunnel to THIS login node (<login-node>) -- one login, -f backgrounds it:

  ssh -N -f -L <UI_PORT>:localhost:<UI_PORT> <user>@<login-node>.rcc.uchicago.edu

then browse:   http://localhost:<UI_PORT>      (pick model '<model>')
==============================================================

`ai-session connect` shows these settings again; `ai-session stop` ends the session.
```

## Step 2: open the SSH tunnel

The UI listens on `127.0.0.1` of the login node, so your browser cannot reach it
directly. Open the tunnel only after the READY block has appeared (or
`ai-session status` reports `READY`); before that nothing is listening on the UI
port and the page does not load. Run the tunnel command that the READY block printed **on your local
machine** (it is already filled in there; the general form is below):

```bash
ssh -N -f -L <UI_PORT>:localhost:<UI_PORT> <user>@<login-node>.rcc.uchicago.edu
```

Replace:

- `<UI_PORT>` with the UI port printed in the READY block.
- `<user>` with your CNetID.
- `<login-node>` with the login node where you started the session (e.g.
  `midway3-login4`); the READY block names it. The RCC login nodes are directly
  reachable — they are the same hosts the `midway3.rcc.uchicago.edu` round-robin
  points at — so this is a single connection with **one login prompt**.

`-N` means "forward ports only, run no remote command"; `-f` backgrounds the tunnel
once it connects, so you can close the terminal (stop it later by killing the ssh
process, e.g. `pkill -f "ssh -N -f -L <UI_PORT>"`).

Connect to the **specific** node the READY block names, not the
`midway3.rcc.uchicago.edu` alias — the alias may land you on a different login node
than the one running your UI. Only if your network cannot reach that node directly,
jump through the alias as a fallback (this authenticates **twice**):
`ssh -N -f -L <UI_PORT>:localhost:<UI_PORT> -J <user>@midway3.rcc.uchicago.edu <user>@<login-node>`.

??? question "What is an SSH tunnel?"
    `ssh -L <port>:localhost:<port> ...` makes your local machine listen on
    `localhost:<port>` and relay every connection through the encrypted SSH
    session to `localhost:<port>` on the remote host. Your browser talks to a
    local port; SSH carries the traffic to the login node where Open WebUI is
    actually listening. Nothing is exposed on any public interface at either end.

!!! note "Working on a login node? Skip the tunnel"
    A browser running on the login node itself (for example under a remote
    desktop) reaches `http://localhost:<UI_PORT>` directly.

Verification, **on your local machine**, in a second terminal:

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:<UI_PORT>
```

Expected output:

```
200
```

## Step 3: chat in the browser

Browse `http://localhost:<UI_PORT>` **on your local machine**. No account or
login is required: the UI runs with authentication disabled and is reachable only
through your own tunnel. The model you started appears in the model picker at the
top of the chat pane; select it and chat.

Chat sessions serve an 8192-token context window (coding sessions serve 32768;
see [Coding Sessions](coding/overview.md)). Your chat history, uploads, and UI
settings persist between sessions in a private per-user database under your home
directory, at `$HOME/.ai-session/openwebui-data` (created mode 700, owner-only).
Storing it in your home directory keeps it readable only by you; other cluster
users cannot read your chats. Because the session URL is stable, the same history
is there the next time you start a session.

Verification: send a message and watch the reply stream in. Every request passes
through the relay, which records its token counts.

## The session access key

Each session start mints a random access key, which is required on every
request. The READY block prints the key and saves it, readable only by you, at
`<state-dir>/logs/gateway/session_key` (mode 600). The Open WebUI that was started
for you already carries the key, so your own browser tab works without any extra
step.

The key is what lets you share one session with your lab. Because several people
may be on the same login node, the gateway binds to `127.0.0.1` and accepts only
requests that carry the key, so no one else on the node can use your session by
accident. To let a labmate use it, give them the key and have them:

1. open their own SSH tunnel to your session's port (`ssh -N -f -L
   <GW_PORT>:localhost:<GW_PORT> <them>@<login-node>.rcc.uchicago.edu`), then
2. set the key as the OpenAI API key in whatever client they use (in Open WebUI,
   Settings > Connections > API Key; for aider or a script, `OPENAI_API_KEY`).

All of their usage is recorded under you, the starter — there is one key per session and no
per-person split. A request without the key is refused with HTTP 401.
`ai-session stop` deletes the key, so it stops working the moment you end the
session; the next start mints a fresh one. `ai-session status` shows only the
first six characters, to confirm a key is set without printing it.

## Step 4: check status

Run this **on the login node** at any time, from any terminal; it only reads state:

```bash
ai-session status
```

It is the ready flag: it answers whether the session is starting, ready, or failed,
and shows whether an access key is set (first six characters only). It prints one
of:

```
session: STARTING -- compiling and warming up the model (1:40 elapsed).
  NOT ready yet: do not open the tunnel. Run `ai-session status` again in a minute.

session: READY -- open the tunnel now.
  on your laptop:  ssh -N -f -L <UI_PORT>:localhost:<UI_PORT> <user>@<login-node>.rcc.uchicago.edu
  then browse:     http://localhost:<UI_PORT>

session: FAILED -- <reason>.
  log: <path to the server log>
```

For a coding session, the `READY` line is followed by `client settings: ai-session
connect` instead of the tunnel command. Raw connection errors in a client while the
status is `STARTING` mean the same thing: the model is still loading.

To verify the gateway directly, poll its health check address **on the login node**:

```bash
curl -sf http://127.0.0.1:<GW_PORT>/__gateway/health
```

Replace `<GW_PORT>` with your port (`ai-session status` prints it when one
is running; `ai-session connect` always prints it). A healthy reply is
HTTP 200 with a JSON body of the form
`{"gateway": "ok", "backend_active": true}` (`false` when no session has published
a backend). This address is reachable without the access key, so it deliberately
reports only liveness — never the model server's internal address.

## Step 5: stop and read the token usage

Run this **on the login node** as soon as you finish:

```bash
ai-session stop
```

`ai-session stop` collects the session's token counts, releases the node, stops
the relay and Open WebUI, and prints the token usage last, so it cannot scroll
away:

```
  TOKEN USAGE -- this session
    model  : <model> (<n> x <GPU type> GPU, or cpu)
    tokens : in=<in> out=<out> total=<total> (<requests> requests)
    session: <job id>
    receipt: <path to summary JSON>
```

The same summary is written to a receipt file under
`~/.ai-session/state/logs/usage/`; `ai-session receipt` prints the newest one
again. No SU figure is printed. The summary file also records the Service Units
computed for RCC staff; see [Billing and Service Units](billing.md).

Verification: run `ai-session status` again; it should report no session running
and no access key set.

## Web search and reference tools (opt-in)

By default the browser chat is fully self-contained: nothing you type leaves RCC.
You can optionally give the chat three tools that reach the internet — start the
session with `AISESSION_TOOLS=1`:

```bash
AISESSION_TOOLS=1 ai-session chat
```

This enables, as per-chat toggles inside Open WebUI:

1. Web search — turn on the search toggle (globe icon) in a message; Open WebUI
   runs the search on the login node, fetches the top results, and feeds them to
   the model. The UI orchestrates this itself, so it works with any model,
   including the 72B `chat` preset. The default engine is keyless DuckDuckGo;
   override `WEB_SEARCH_ENGINE` (e.g. `searxng`, `tavily`) and its key/URL for
   another provider.
2. URL fetch — paste a link in a message and the page is loaded and summarized.
   This also works with any model.
3. Reference search — an academic paper search (arXiv, bioRxiv, medRxiv, PubMed,
   Semantic Scholar) appears under the message Tools menu. Open WebUI can drive
   it with any model. For the model to place the tool calls itself, start the
   session with a tool-calling model and the `--agent` flag —
   `AISESSION_TOOLS=1 ai-session chat --model qwen3.8_27B --agent` — since the
   72B `chat` preset does not emit tool calls reliably.

!!! warning "These tools send data outside RCC — it is why they are off by default"
    Web search, URL fetch, and reference lookups send your query terms (and, for
    URL fetch, the requested address) to services outside RCC — the search engine,
    the fetched site, or the scholarly APIs. The model itself still runs on-cluster and
    your prompts are not sent wholesale, but these specific tool requests leave RCC. Use
    them only for non-sensitive queries. Self-hosting SearXNG (`WEB_SEARCH_ENGINE=searxng`)
    or restricting to the scholarly sources narrows the exposure. Without
    `AISESSION_TOOLS=1`, none of this is active and the session stays fully local.

## Trying the service without a GPU

To try the browser chat, or to check that a coding client is wired up, without
waiting for or holding a GPU, add `--cpu` and name a CPU-only partition (`amd` or
`caslake`) the first time:

```bash
ai-session chat --cpu --account <your-account> --partition amd
```

The CPU partition is remembered as `CPU_PARTITION` in `~/.ai-session/config`,
separately from your GPU partition, so later runs need only `ai-session chat --cpu`.
The same flag works on `code` and `fast` (e.g. `ai-session code --cpu --agent`).

| Property | Value |
|---|---|
| Model | Qwen2.5 0.5B Instruct (`qwen2.5_0.5B`) only; any other `--model` is refused |
| `--lora` | Refused |
| Time to READY (measured on `amd`, 16 cores) | about 2 to 3 minutes after the job starts |
| Short browser-chat reply | a few seconds |

The startup banner, `ai-session status`, and the token usage at `ai-session stop`
behave exactly as on a GPU session. On a CPU session, opencode and Claude Code run
with their tools turned off, because the tool definitions make up most of their
prompt and the 0.5B model cannot use tools reliably. The CPU mode is for trying
the service; use a GPU session for real work. Details are in the
[Command Reference](reference.md#trying-the-service-without-a-gpu).

## Where each piece runs

| Piece | Runs on | Holds cluster resources |
|---|---|---|
| Model server | GPU node (or CPU node with `--cpu`) | Yes, until `ai-session stop` |
| Gateway | Login node | No |
| Open WebUI | Login node | No |
| `ai-session status` / `stop` | Login node | No |

If a step fails — the READY block never appears, a port is already in use, the
browser cannot connect, or the model is missing from the picker — see
[Troubleshooting](troubleshooting.md).
