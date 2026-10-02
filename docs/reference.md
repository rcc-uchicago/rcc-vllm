# Command Reference

This page contains user-facing command of the ai-session service in one
place: the `ai-session` command and its arguments. The specific paths are covered end to end on
[Getting Started](getting-started.md) (browser chat) and
[Coding Sessions](coding/overview.md).

All commands on this page run **on the login node**. A session serves one model
on cluster GPUs; the gateway — the small always-on relay the service runs on the
login node at a fixed per-user port — forwards requests to wherever the current
session is running, so clients keep one stable address. When a session ends,
`ai-session stop` reports the tokens it consumed; how RCC staff account for
sessions is on [Billing and Service Units](billing.md).

## Setup

Once per shell:

```bash
module load ai-session
```

This puts `ai-session` on your PATH and sets `AISESSION_HOME` to the shared
install.

## Command summary

| Task | Command | Holds |
|---|---|---|
| Start a general chat session (browser UI) | `ai-session chat` | 4 GPUs (`qwen2.5_72B`) until stopped |
| Start a coding session (aider/Continue/opencode/Claude Code) | `ai-session code` | 2 GPUs (`qwen3.8_27B`) until stopped |
| Start a small chat session | `ai-session fast` | 1 GPU (`qwen3_4b`) until stopped |
| Any of the three on a CPU node | add `--cpu` | one CPU node (`qwen2.5_0.5B`) until stopped |
| Is the session ready, loading, or stopped? | `ai-session status` | nothing |
| Print client setup (URL, key, per-client commands) | `ai-session connect` | nothing |
| Export the client settings into this shell | `eval "$(ai-session env)"` | nothing |
| Run Claude Code against the session's model | `ai-session claude` | nothing |
| List the model presets | `ai-session models` | nothing |
| Re-print the newest token-usage receipt | `ai-session receipt` | nothing |
| Print the agent tool-server (MCP) config block | `ai-session mcp config` | nothing |
| Run a built-in tool server (agents call this) | `ai-session mcp run jobs` / `ai-session mcp run usage` | nothing |
| Stop the session, free the node, print the tokens consumed | `ai-session stop` | releases the node |

The accepted arguments:

| Option | Default | Purpose |
|---|---|---|
| `--account NAME` | none — required once | Your Slurm account. Required on the first session, then remembered in `~/.ai-session/config`; there is no default because the account is unique per user/PI. |
| `--partition NAME` | none — required once | The GPU partition to run in. Required on the first session, then remembered. |
| `--time HH:MM:SS` | `02:00:00` | Session time limit. The session ends when it expires even if you forget `stop`, which caps how long a forgotten session holds its node. |
| `--model KEY` | the preset's model | Serve a different registered model (table below); the GPU configuration is chosen for you. |
| `--agent` | off | Enable native tool calling: required by [opencode and Cline](coding/opencode.md) (not by aider or Continue), and used on `chat` for the model to call the opt-in [reference tools](getting-started.md#web-search-and-reference-tools-opt-in) itself. |
| `--lora NAME=PATH` | none | Also serve your own fine-tuned adapter under the name `NAME`; repeatable. Validated before anything is reserved. See [Your Own Fine-Tuned Model](lora.md). |
| `--cpu` | off | Run on a CPU-only partition instead of a GPU. Serves `qwen2.5_0.5B` only (any other `--model` is refused), and reserves no GPU; `ai-session stop` reports the tokens the job consumed (input, output, requests). Give a CPU partition with `--partition` (`amd` or `caslake`); it is remembered separately from your GPU partition. Not combinable with `--lora`. See [Trying the service without a GPU](#trying-the-service-without-a-gpu). |

!!! warning "A running session holds its node whether or not you send requests"
    Every start verb reserves its GPUs (or, with `--cpu`, its CPU node) and holds
    them, busy or idle, until you run `ai-session stop` or `--time` expires; no one
    else can use them meanwhile. `ai-session stop` frees the node and prints the
    tokens the session consumed.

## Start-up progress and `ai-session status`

A start verb waits on the login node until the session is usable, which takes a
few minutes. While it waits it prints a banner -- for `chat` and `fast`:

```text
vLLM is starting -- PLEASE WAIT. The web page is NOT ready yet. Do not open the SSH
tunnel or the browser until you see the READY box with the tunnel command.
```

and for `code` the same banner says the session is not ready and not to start
opencode or aider (or open an SSH tunnel) until the READY box with the connection
settings appears. Below it, one progress line per stage with the elapsed time, for
example `[1:40] compiling and warming up the model ...`. The stages, in order:

1. waiting for a compute node
2. loading the model weights
3. compiling and warming up the model
4. starting the API server
5. finishing start-up

For `chat`, once the model is loaded the terminal adds "The model is loaded, but the
web page is still NOT ready -- please wait for the READY box." while the browser UI
starts. If the model server exits while loading, start-up stops at once and prints
the path to its log, rather than waiting out the time-out.

`ai-session status` is the ready flag, and works from any shell on the same login
node. It prints one of three states:

| Output | Meaning |
|---|---|
| `session: STARTING -- <stage> (m:ss elapsed).` followed by `NOT ready yet: do not open the tunnel.` | Still starting; run `ai-session status` again in a minute. |
| `session: READY -- open the tunnel now.` | Usable. For `chat` it also prints the exact `ssh -N -f -L ...` command and the browser URL; for `code` it points to `ai-session connect` for the client settings. |
| `session: FAILED -- <reason>.` followed by `log: <path>` | Start-up failed; the log path is the model server's log. See [Troubleshooting](troubleshooting.md). |

When no start-up is in progress it reports the gateway's view instead (for example
`session: none running`), the first six characters of the access key, and your
session jobs in the queue.

## Where session state lives

The LLM, coding tools, model weights, and the serving environment are
shared and read-only, while everything a session writes goes to a per-user
directory.

- `AISESSION_STATE_DIR` is the per-user writable root — `~/.ai-session/state`
  under your own home directory by default, so a session needs no write access to
  the shared install. It holds session records, the gateway pointer, per-request
  usage capture, token-usage receipts, and server logs. Set it to a scratch path if
  your home quota is tight.
- `~/.ai-session/env` (mode 600) holds the current session's client settings —
  written by the start verbs and refreshed by `ai-session env` and
  `ai-session connect`. Its contents are the variables listed under
  [Client settings](#client-settings-ai-session-env).
- Token-usage receipts are written as
  `~/.ai-session/state/logs/usage/<user>_<jobid>_<timestamp>_summary.json`
  (under `AISESSION_STATE_DIR` if you moved it).
- Default ports are derived from your numeric user ID so two users on one login
  node do not collide: the gateway listens on `GW_PORT = 8400 + UID % 90` and the
  browser UI on `3000 + UID % 90`. Print yours with
  `echo $((8400 + $(id -u) % 90)) $((3000 + $(id -u) % 90))`.

## Trying the service without a GPU

`--cpu` starts the same session -- gateway, access key, browser chat, and the
client settings from `ai-session connect` -- on a CPU-only node, serving the small
Qwen2.5 0.5B Instruct model. It holds no GPU, so it is the way to try the browser
chat or to check that opencode, aider or Claude Code are wired up before starting a
GPU session. When you stop it, `ai-session stop` reports the tokens the job
consumed -- input, output and the number of requests -- as it does for a GPU
session.

The partition must be a CPU-only one, `amd` or `caslake`. Give it with
`--partition` the first time; it is remembered as `CPU_PARTITION` in
`~/.ai-session/config`, separately from your GPU partition. Any `--model` other
than `qwen2.5_0.5B` is refused, and so is `--lora`.

1. Start a browser chat on the `amd` partition (the first time, also give `--account`):

        ai-session chat --cpu --account <acct> --partition amd

2. Or start a coding session (`--agent` is needed for opencode and Claude Code), then
   in the same shell load the settings and run a client:

        ai-session code --cpu --agent --partition amd
        eval "$(ai-session env)"
        opencode            # first: module load opencode
        aider
        ai-session claude

3. Stop it as usual with `ai-session stop`.

!!! note "On a CPU session, opencode and Claude Code run without tools"
    Their tool definitions are most of their prompt, and reading a long prompt
    takes minutes on CPU. On a `--cpu` session `ai-session env` gives opencode a
    configuration with tools turned off, and `ai-session claude` starts Claude Code
    with tools turned off. The 0.5B model cannot use tools reliably in any case.

Measured on `amd` (16 cores, vLLM 0.26.0 CPU build, 2026-10-01):

| Client | Prompt per request | Reply time |
|---|---:|---:|
| Browser chat, short question | short | seconds |
| opencode, tools on | 15,122 tokens | about 2.5 min |
| opencode, tools off (what `--cpu` uses) | 2,006 tokens | 4 s |
| Claude Code, tools on | 15,000-24,000 tokens | 229 s |
| Claude Code, tools off (what `--cpu` uses) | 5,859 tokens | 32 s |

The model is ready about 2-3 minutes after the job starts. The 0.5B model answers
simple prompts but does no useful coding work, so treat `--cpu` as a way to try the
service and check client wiring, not as a working coding assistant.

## Models

`--model` takes a registry key:

| Key | Model | Available | License |
|---|---|---|---|
| `qwen2.5_72B` | Qwen2.5-72B-Instruct | Yes (`chat` preset) | Qwen (Tongyi) community license |
| `qwen3.8_27B` | Qwen3.8-27B | Yes (`code` preset, default); thinking model with `reasoning_effort` low/medium/xhigh; accepts images; A100 TP=2 (H100 also works, via `CONSTRAINT=H100`) | Apache-2.0 |
| `gemma4_31B` | Gemma-4-31B-it | Yes (`code --model gemma4_31B`); second coding option; thinking OFF by default, opt-in; accepts images; A40 or A100, TP=2 | Apache-2.0 |
| `qwen3_4b` | Qwen3-4B | Yes (`fast` preset; also `code --model qwen3_4b` for cheap coding) | Apache-2.0 |
| `qwen3.5_122B` | Qwen3.5-122B-A10B (FP8) | **Requires H100 or H200** (FP8 will not run on Ampere) — see [Which GPUs each model needs](#which-gpus-each-model-needs). Validated at TP=2 on both Hopper tiers; awaiting a billing rate before it joins the served set | Apache-2.0 |
| `qwen2.5_0.5B` | Qwen2.5-0.5B-Instruct | Yes; the only model `--cpu` serves. Answers are basic -- use it to try the service and wire up clients, not for real work | Apache-2.0 |

The license terms and the obligations that apply when you serve these models to
other people are set out on [Model licenses](licenses.md). Every model offered is
Apache-2.0 except `qwen2.5_72B`, which is under the Qwen (Tongyi) community license.
No model requires a per-user acknowledgment.

### The coding models

`qwen3.8_27B` (Qwen3.8-27B) is the `code` preset default. On a frozen 60-problem
LiveCodeBench subset, scored by an identical harness on an identical serve environment, it
reaches 50.0% pass@1. It was the best of six candidates evaluated, and it beat the much
larger `qwen3.5_122B` (45.0%) at under half the footprint, though that 5-point gap sits
inside the measurement's noise band. It is a thinking model whose reasoning depth is
adjustable per request (`reasoning_effort`: `low`, `medium`, or `xhigh`, its default), and a
vision-language model that accepts images and video alongside text. It serves BF16 at TP=2
under vLLM 0.26.0, which the launcher selects automatically for this model family, and its
tool calling works natively with the `qwen3_coder` parser, also selected automatically.

It runs on **A100** by default (measured: 25.7 GiB of weights per GPU at TP=2, leaving
44 GiB of KV cache — over a million tokens). A100 is the default rather than the faster
H100 for a practical reason: H100 nodes on this cluster belong to individual research
groups, so an H100 default would make the coding model unstartable for most users. Pass
`CONSTRAINT=H100` if you have access to that tier and want it.

Two caveats worth knowing.

1. **Billing.** Its measured rate record is for the H100 tier, so an A100 session bills
   the reservation floor (GPU time held) with no token-metered component until an A100
   record is measured. The A100 floor is half the H100 floor, so this is not a penalty.
2. **Benchmark figure.** The 50.0% was measured with thinking *disabled*, which is not
   this model's default mode. Treat it as a lower bound.

`gemma4_31B` (Gemma-4-31B-it) is the second coding option, reached with
`ai-session code --model gemma4_31B`. It scored 66.7% on the same frozen subset, also
accepts images, and also serves BF16 at TP=2. Two things distinguish it: its thinking mode
is **off** by default and opt-in per request, and it runs on **A40**, where it is both
faster and half the price of the same model on A100. That comparison — including why the
66.7% and the 50.0% above are not like-for-like — is set out on
[Choosing between the two coding models](coding/overview.md#choosing-between-the-two-coding-models).
It has measured rate records for the a40 and a100 tiers at TP=2; on any other tier it bills
the reservation floor.

!!! warning "Delete any `AGENTS.md` tool-call workaround file you still have"
    Earlier versions of these instructions asked for an `AGENTS.md` file in your repository
    root that told the model to spell out `<tool_call>` tags character by character. Both
    coding models emit tool calls natively, so that file now instructs the model to
    hand-write a format that is not its own — at best noise, and actively counterproductive
    with the current models. Delete it. `AGENTS.md` remains fine for ordinary project
    instructions.

### Which GPUs each model needs

Most models here are BF16 and run on any GPU tier the cluster offers; the service picks a
sensible default so you do not have to. One model is different.

| Model key | Weights | Runs on | Default | Who can start it |
|---|---|---|---|---|
| `qwen3.8_27B` | BF16 | any bf16 GPU | 2 × A100 | anyone with GPU access |
| `qwen2.5_72B` | BF16 | any bf16 GPU | 4 × A100 | anyone with GPU access |
| `qwen3_4b` | BF16 | any bf16 GPU | 1 × A100 | anyone with GPU access |
| `gemma4_31B` | BF16 | any bf16 GPU | 2 × A40 or A100 | anyone with GPU access |
| `qwen3.5_122B` | **FP8** | **H100 or H200 only** | 2 × Hopper GPUs | **only users with H100/H200 access** |

`qwen3.5_122B` ships with native FP8 weights, and FP8 arithmetic needs Hopper-generation
tensor cores. A100 and A40 are Ampere and have none, so this model cannot run on them at
any tensor-parallel size — it is a hardware requirement, not a tuning choice. Attempting it
on Ampere fails during model load.

On this cluster, H100 and H200 nodes belong to individual research groups. So in practice
`qwen3.5_122B` is startable only if your group owns Hopper hardware and you submit against
that account and partition. If you are not sure whether you have such access, you almost
certainly do not, and `qwen3.8_27B` is the model you want — it scored higher on our own
coding benchmark anyway (50.0% vs 45.0%).

Everything else runs on A100, which is available through the `beagle3` partition and the
open `gpu` partition. No special access is needed.

`qwen3.5_122B` is registered and validated on both Hopper tiers at TP=2: on two H200s
(58.24 GiB of weights per GPU, 62.89 GiB of KV cache) and on two H100 NVL cards (same
weights, 20.85 GiB of KV — just over a million tokens). It is not in the served set because
it has no measured billing rate.

### Rough capability frame of reference

These positionings are approximate, drawn from public 2026 leaderboards and
third-party comparisons rather than from a controlled evaluation on this hardware,
and capability differs by task — use them to pick a model, not as a claim of
parity.

| Served / staged model | Rough closed-weight analog | Basis (approximate) |
|---|---|---|
| `qwen3_4b` | GPT-4o-mini class (light tasks) | 4B thinking model; strong on math for its size |
| `qwen3.8_27B` *(coding default)* | 2026 open-weight frontier for its size | 50.0% pass@1 on our frozen LiveCodeBench subset, measured thinking-off and so a lower bound; vendor-reported SWE-bench Pro 61.7 and Terminal-Bench 2.1 73.0, above the much larger Qwen3.7-Plus on both. Vendor figures are self-reported and no independent code-specific evaluation exists yet. |
| `gemma4_31B` *(second coding option)* | 2026 open-weight frontier for its size | 66.7% pass@1 on the same frozen subset, measured thinking-off — which is this model's own default but not Qwen's, so the two figures are not like-for-like |
| `qwen2.5_72B` | GPT-4-turbo / GPT-4o-mini (general) | strong 2024 general model, a generation behind 2026 frontier |
| `qwen3.5_122B` *(validated; cutover pending)* | ≈ Claude Sonnet 4.5 / GPT-5-mini tier | vision-language mixture-of-experts model (accepts images); scores higher than GPT-5-mini on the BFCL-V4 tool-use benchmark (72.2 vs 55.5), lower than Claude Opus |

The trade is capability for locality: the closed models above score higher on most
tasks, while these run entirely on RCC hardware, so no data leaves the cluster and
usage is accounted in SU rather than paid per token.

To serve a model you fine-tuned yourself alongside its base model, add
`--lora NAME=PATH` ; requests whose model is `NAME` are answered
by your fine-tune. Requirements and examples are on
[Your Own Fine-Tuned Model](lora.md).

### Thinking, and where the reasoning text goes

`qwen3.8_27B` and `qwen3_4b` think before answering and are served with a reasoning
parser, so the chain of thought is returned in a separate `reasoning_content` field and the
answer stays in `content` — the raw `<think>…</think>` block is not mixed into the reply.
`gemma4_31B` can think but does not by default; you opt in per request, and the
[coding overview](coding/overview.md#choosing-between-the-two-coding-models) records what
that costs. The Qwen2.5 models do not think. Clients differ in whether they surface
`reasoning_content`: opencode displays it as a Thinking block (`opencode run --thinking`, or
in its TUI), while aider shows only the answer. See
[opencode](coding/opencode.md#seeing-the-models-reasoning).

## The session access key

Each session start mints a random access key; the gateway requires it on every
request and refuses requests without it (HTTP 401). The start verbs print it in
the READY block and save it readable only by you; `ai-session connect` re-prints
it, `ai-session env` exports it as `AISESSION_API_KEY`, and `ai-session status`
shows its first six characters. Share it with your lab to let them use your
session over their own tunnel — their tokens are counted in your session's usage.
`ai-session stop` deletes the key, and the next start mints a fresh one.

## Client settings (`ai-session env`)

`eval "$(ai-session env)"` loads the running session's settings into the current
shell. After it, opencode and aider need no configuration file and no flags. It
exports:

| Variable | Value | Used by |
|---|---|---|
| `AISESSION_BASE_URL` | `http://localhost:<GW_PORT>/v1` | scripts, curl, Python |
| `AISESSION_API_KEY` | the session access key | scripts, curl, Python |
| `AISESSION_MODEL` | the served model key, e.g. `qwen3.8_27B` | scripts, curl, Python |
| `AISESSION_DEVICE` | `gpu` or `cpu` | `ai-session claude` (tools off on `cpu`) |
| `OPENCODE_CONFIG_CONTENT` | an inline opencode configuration that points at the session (tools off on a `--cpu` session) | opencode |
| `OPENAI_API_BASE`, `OPENAI_API_KEY` | the session URL and access key | aider |
| `AIDER_MODEL`, `AIDER_WEAK_MODEL` | `openai/<model>` | aider |
| `AIDER_MODEL_METADATA_FILE` | the shared model-metadata file | aider |
| `AIDER_EDIT_FORMAT` | `diff` | aider |
| `AIDER_ANALYTICS_DISABLE` | `true` | aider |

Three consequences worth knowing:

1. `OPENAI_API_KEY` is overwritten in that shell. If you also use the OpenAI API
   from the same shell, open a new one or re-export your own key afterwards.
2. `OPENCODE_CONFIG_CONTENT` takes precedence over an `opencode.json` in your
   repository, so a repository file that pins another model does not redirect
   opencode away from the session. opencode shows the model under its real name
   (e.g. `qwen2.5_0.5B`). opencode needs a session started with `--agent`.
3. aider does not need the `eval` at all: the `aider` that `module load ai-session`
   provides reads the running session's settings itself each time it starts, and
   if no session is running it says so. Flags on its command line still win (for
   example `--edit-format whole`).

On your laptop, open the tunnel printed in the READY box, then copy the settings
that `ai-session connect` prints.

## Claude Code (`ai-session claude`)

`ai-session claude` runs Claude Code against the running session's model. The
model server answers the Anthropic Messages API (`/v1/messages`) and the gateway
forwards it with the same access key, so token usage is recorded like any other
request.

1. Start a coding session with tool calling (on a GPU for real work):

        ai-session code --agent

2. When it is READY, run Claude Code against it:

        ai-session claude

    Extra arguments are passed to Claude Code, for example
    `ai-session claude -p "Explain this repository's build"`.

The settings apply to that one run only. `ai-session claude` points Claude Code at
the gateway with the session key and model, caps each reply at 4,096 output tokens,
turns off non-essential network traffic, shows the model as
`<model> (ai-session)` in `/model` and the status line, and uses its own
configuration directory, `~/.ai-session/claude`. Your normal Claude Code login,
history, plugins and hooks are not touched, and a later plain `claude` talks to
Anthropic as usual. The first interactive run shows Claude Code's one-time setup
screens.

It requires Claude Code to be installed (`claude` on your PATH); if it is not,
`ai-session claude` prints the install command:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

On a GPU session Claude Code has its tools. On a `--cpu` session it runs without
tools (see [Trying the service without a GPU](#trying-the-service-without-a-gpu)),
which is enough to check the connection but not to do coding work.

## Scripted access with curl and Python

Any client that speaks the standard OpenAI API format works against the session
URL. After `eval "$(ai-session env)"`, the base URL is `$AISESSION_BASE_URL`
(`http://localhost:<GW_PORT>/v1`) on the login node where you started the
session; from your laptop, tunnel the port first:

```bash
ssh -N -L <GW_PORT>:localhost:<GW_PORT> <cnetid>@<login-node>.rcc.uchicago.edu
```

- Replace `<GW_PORT>` with your session port (`echo $((8400 + $(id -u) % 90))`).
- Replace `<cnetid>` with your CNetID.
- Replace `<login-node>` with the login node where you started the session (the
  start verbs print it; `hostname -s` on that node shows it).

List the served model — run this **on the login node** (or on your laptop through
the tunnel, with the two variables set to the values `ai-session connect` prints):

```bash
curl -s "$AISESSION_BASE_URL/models" -H "Authorization: Bearer $AISESSION_API_KEY"
```

Expected output (trimmed):

```
{"object": "list", "data": [{"id": "qwen3.8_27B", "object": "model", ...}]}
```

A minimal chat completion with the `openai` Python package (install it in your
own environment):

```python title="chat_example.py"
import os
from openai import OpenAI

client = OpenAI(base_url=os.environ["AISESSION_BASE_URL"],
                api_key=os.environ["AISESSION_API_KEY"])
resp = client.chat.completions.create(
    model=os.environ["AISESSION_MODEL"],
    messages=[{"role": "user", "content": "Write a one-line docstring for a matrix transpose function."}],
)
print(resp.choices[0].message.content)
print(resp.usage)
```

The gateway records per-request token usage automatically: every chat/completions
response's `usage` object is appended to a per-day usage log under your state
directory, and for streaming requests the gateway asks the engine to report usage
in the final stream chunk. `ai-session stop` totals this log for the token-usage
receipt, so scripted clients need no usage instrumentation of their own. Server-side tool
calling for agent frameworks requires a session started with
`ai-session code --agent`; see the [coding agents guide](coding/opencode.md).

??? question "What does the gateway do with paths other than /v1?"
    The gateway proxies `/v1`, `/metrics`, `/health`, `/version`, `/ping`,
    `/tokenize`, `/detokenize`, and `/pooling` to the current backend; other paths
    return 404, and the bare `/` returns a JSON hint. Its own health check is
    `GET /__gateway/health`, which reports gateway liveness and whether a backend
    is published (`{"gateway":"ok","backend_active":true|false}`) but not the
    backend's internal address — that endpoint needs no key, so the address is
    withheld. A keyless structured-status route, `GET /status`, answers
    `ready` / `loading` / `no_backend`, which is what `ai-session status` shows.
    When no session is active, proxied requests return 503 with
    `"type": "no_backend"`; see [Troubleshooting](troubleshooting.md).

## Checking token usage

`ai-session stop` ends the session and prints its token usage as its last output:

```text
==============================================================
  TOKEN USAGE -- this session
    model  : <model_key> (<n> x <gpu type> GPU | cpu)
    tokens : in=<T_in> out=<T_out> total=<T_in + T_out> (<n> requests)
    session: <job id>
    receipt: <path to the summary JSON>
==============================================================
```

`ai-session receipt` re-prints the newest receipt, and `ai-session receipt <file>`
renders an older one. The receipt file is the per-session summary JSON,
`~/.ai-session/state/logs/usage/<user>_<jobid>_<timestamp>_summary.json`. No SU
figure is printed; the SU accounting RCC staff keep is described on
[Billing and Service Units](billing.md).

## For administrators

The advanced launcher (per-flag control of the serving configuration, GPU type
selection, serving context length, memory utilization, alternative accounts and
partitions), the raw wrapper scripts and their environment variables, gateway
internals, the billing benchmark, and rate-table maintenance are documented in
the staff guide, `ai-session/README.md` in the service repository. The billing
policy and rate table are editable by RCC staff only. Users never need these; if
a preset does not fit your case, ask RCC staff.
