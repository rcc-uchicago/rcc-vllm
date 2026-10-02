# AI Sessions on RCC

ai-session is a local large-language-model service on the University of Chicago Research
Computing Cluster (RCC). Instead of sending data to a commercial provider faculty and students run open LLM models on the GPUs the university already has.
Compared with a cloud AI service: your prompts, code, and data never leave the
university's systems; usage is reported
to you as the tokens each session consumes; and the served models are open-weights
checkpoints, so the exact model behind a result can be named and served again (for provenance and publishing your research online). 
You start a session, which serves a model on cluster GPUs, which is reached via ssh-tunnel. For chatting with the LLM you have two ways:
browser chat with Open WebUI ([Getting Started](getting-started.md)) or command-line/in-editor coding tools ([Coding Sessions](coding/overview.md)).

## Starting a session

From a login node:

```bash
module load ai-session

ai-session chat      # chat in your browser, or:
ai-session code      # a coding session for aider / Continue / opencode / Claude Code

ai-session status    # STARTING, READY, or FAILED? (the model takes a few minutes to load)
ai-session stop      # done -- free the node and print the tokens consumed
```

Starting a session takes a few minutes while the model loads. The terminal shows a
"PLEASE WAIT ... NOT ready yet" banner and progress lines with the current stage;
when the model is up it prints a READY box with everything you need — the web
address, the session access key, and (for laptops) the SSH command that makes the
address reachable from your machine. Do not open the tunnel or start a client
before the READY box appears. The per-client details are on the pages under
[Choose your path](#choose-your-path).

To try the service without a GPU, `ai-session chat --cpu --partition amd` serves
the small Qwen2.5 0.5B model on a CPU-only node; see
[Getting Started](getting-started.md#trying-the-service-without-a-gpu). The per-client details are on the pages under
[Choose your path](#choose-your-path).

## How it works

Three pieces are involved:

```
client                     gateway (login node)           model server (GPU node)
your laptop/login     ->   http://localhost:<port>/v1  -> moves every session
(browser/aider/...)        stable URL, relay              GPU-backed (or CPU)
```

- The **model server** runs on a GPU node inside the cluster and answers
  requests in the standard OpenAI API format that most AI tools can talk to.
  Its address changes every session, and it is not reachable from outside the
  cluster.
- The **gateway** is a small always-on relay on a login node at a fixed port;
  it exists because the model server moves — it forwards to whichever server
  the current session is using, so the client sees one web address that never
  changes between sessions, and it records per-request token usage.
- The **client** — a browser chat window or a coding tool — reaches that address
  over `localhost` on the login node or an SSH-forwarded port from your laptop.
  No client configuration file is needed: the browser UI is started for you,
  `aider` and `ai-session claude` (Claude Code) pick up the running session
  themselves, and `eval "$(ai-session env)"` sets up opencode and other tools.

## Data location

The LLM executes on a RCC GPU node. The gateway executes on an RCC login
node. The client reaches it over `localhost` or an SSH-forwarded port.
Along this serving path — client to gateway to model server — no prompt, file
content, or completion is transmitted to any service outside RCC. This is the main
difference from hosted assistants and is the reason the service is
appropriate for unpublished or otherwise restricted code and data. The one
exception is opt-in: starting browser chat with `AISESSION_TOOLS=1` adds web and
reference tools whose query terms do leave RCC; see
[Getting Started](getting-started.md#web-search-and-reference-tools-opt-in).

!!! note "Coding-tool monitor with external servers is a separate concern you control in your client"
    The statement above covers the serving path — the model traffic itself. The
    coding tool you run as the client (aider, Continue, opencode, Claude Code) is separate
    software that may have its own usage telemetry, which independently could send
    model traffic and is outside this service's control. Disable it in your
    own client: the `aider` provided by `module load ai-session` runs with analytics
    disabled (`AIDER_ANALYTICS_DISABLE`), `ai-session claude` disables Claude Code's
    non-essential traffic, the
    documented Continue configuration sets `allowAnonymousTelemetry: false`, and the
    Open WebUI instance the browser launcher starts already has telemetry disabled
    (`ANONYMIZED_TELEMETRY=False`, `DO_NOT_TRACK`, `SCARF_NO_ANALYTICS`). Check your
    client's own settings for anything not covered here.

## Available models

Each preset picks a model and the right number and type of GPUs for it; you never
configure GPUs yourself. The model key is the name the API serves under and the
value you pass to `ai-session <preset> --model` when you want something other than
the preset's default.

| Preset | Model key | Weights | Use | Context (tokens) | GPUs it runs on | License |
|---|---|---|---|---:|---|---|
| `code` | `qwen3.8_27B` | Qwen3.8-27B | Coding (default) | 32768 | 2 x A100 | Apache-2.0 |
| `code --model gemma4_31B` | `gemma4_31B` | Gemma-4-31B-it | Coding (alternative) | 32768 | 2 x A40 or A100 | Apache-2.0 |
| `chat` | `qwen2.5_72B` | Qwen2.5-72B-Instruct | General chat | 8192 | 4 x A100-80GB | Qwen (Tongyi) community license |
| `fast` | `qwen3_4b` | Qwen3-4B | Small and fast; lowest cost | 8192 | 1 x A100 | Apache-2.0 |

A good practice is to start small and scale up: prototype your prompts,
scripts, or agent setup against `ai-session fast` — the small model loads
quickest, waits least for free GPUs, and holds a single GPU — and move to a coding model or the 72B once the workflow works. The larger
models are more capable, and switching requires no change to the client
configuration.

The default coding model is itself a thinking model: its chain of thought is returned
separately from the answer, and reasoning depth is adjustable per request via
`reasoning_effort` (`low`, `medium`, or `xhigh` — `xhigh` is the model's default). The
second coding option, Gemma-4-31B, does not think unless you ask it to, which makes it
cheaper and faster for routine work; it also runs on A40, the least expensive GPU tier
here. Both accept images. Which to pick is covered on the
[coding overview](coding/overview.md#choosing-between-the-two-coding-models).
A fifth model, Qwen2.5-0.5B-Instruct (`qwen2.5_0.5B`, Apache-2.0), is served by
`--cpu` sessions on CPU-only partitions; it is for trying the service and checking
client setup, not for real work. See
[Trying the service without a GPU](getting-started.md#trying-the-service-without-a-gpu).

One larger model is staged but not yet offered. Qwen3.5-122B-A10B is validated at two
GPUs on both Hopper tiers and joins the served list once it has a measured rate.
Note that its weights are FP8, which requires an H100 or H200 — it cannot run on A100 or
A40 at all. Since Hopper nodes here belong to individual research groups, this model will
only ever be startable by users whose group owns that hardware. Everything else the
service offers runs on A100, which needs no special access.

Guidance on choosing between the served models is on the
[coding overview](coding/overview.md) page, and a rough capability frame of
reference against closed "frontier" models is in the
[Command Reference](reference.md#rough-capability-frame-of-reference). Every model
offered is Apache-2.0 except Qwen2.5-72B, which carries an attribution obligation when
you serve it to other people; the details are on the
[model licenses](licenses.md) page.

!!! note "GPU nodes have no internet access"
    Only pre-staged models can be served; a session cannot download weights. New
    models are staged by RCC staff on request.

## What it costs, in one line

A session holds its node (its GPUs, or a CPU node with `--cpu`) from the moment
it starts until you stop it, and `ai-session stop` reports the tokens it consumed
(input, output, total, and number of requests). No Service Unit figure is shown
to users at start or stop; SU are still computed and recorded for RCC staff. The
SU policy, GPU weights, and rate table are on the [billing page](billing.md).

!!! warning "A running session holds its node whether or not you send requests"
    The GPUs stay reserved for the session's whole wall-clock lifetime, unavailable
    to anyone else. Stop your session with `ai-session stop` as soon as you finish
    working.

!!! note "ai-session SUs are not RCC allocation Service Units"
    The SUs described here are the ai-session service's own fair-usage
    accounting, defined in its [billing policy](billing.md); they are not
    deducted from any RCC allocation.

## Choose your path

| You want | Start here |
|---|---|
| Chat with a model in the browser (Open WebUI) | [Getting Started: Browser Chat](getting-started.md) |
| Use a coding tool (aider, Continue, opencode, Claude Code) against your own repository | [Coding Sessions](coding/overview.md) |
| Serve a model you fine-tuned yourself | [Your Own Fine-Tuned Model](lora.md) |

The [command reference](reference.md) lists every command in one place, and
[troubleshooting](troubleshooting.md) collects the known failure symptoms and
their resolutions.

## Getting help

Open a ticket through the standard RCC support channel. Mention `ai-session` if
the question is about the service itself — sessions, models, connection problems
beyond the [troubleshooting page](troubleshooting.md), or billing — so it reaches
the staff who maintain it. Questions about the cluster in general — accounts,
SSH access, RCC allocations — follow the normal help-desk path.
