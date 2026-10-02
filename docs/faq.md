# Frequently asked questions

This page collects the questions new users ask most often. If your question is about a
specific client, the [Coding Sessions](coding/overview.md) pages and
[Getting Started](getting-started.md) go into more depth; for the accounting policy see
[Billing and Service Units](billing.md); for failures see
[Troubleshooting](troubleshooting.md).

## Access and cost

### Who runs this, and how do I get help?

The service is run by RCC staff. For access requests, problems the
[Troubleshooting](troubleshooting.md) page does not solve, or requests that need
RCC staff (a new model, a larger fine-tuned adapter, a longer time limit), open a
ticket through the standard RCC support channel and mention `ai-session`.

### How do I get access?

You need an RCC account (no special group membership is required) and a Slurm
account and GPU partition to run the GPU job under — the latter are unique to
you and your PI, so you supply them the
first time you start a session (`--account` and `--partition`, then remembered).
Once you have those, you load the module and start a session as described in
[Getting Started](getting-started.md). There is no separate signup step.

### What will a session cost? What usage do I see?

Usage is reported to you as tokens. No estimate is printed before the job starts; when you
run `ai-session stop`, a TOKEN USAGE box shows the model, where it ran (for example
`2 x a100 GPU`, or `cpu`), the input, output, and total tokens, the number of requests, the
job id, and the receipt file path. `ai-session receipt` prints the newest receipt again.
Service Units (SU) are still computed and recorded in the receipt file and the RCC staff
ledger, but they are not shown to users; the policy is in
[Billing and Service Units](billing.md).

### How do I use the cluster considerately?

Run `ai-session stop` the moment you stop working. An idle session still holds its GPUs
(or its CPU node), and no one else can use them until it ends. Prefer the smallest
configuration that does the job: `ai-session fast` holds one GPU, and the capable coding
configuration with the lightest footprint is Gemma-4-31B on two A40 cards. To try the
service or test client setup, `--cpu` holds no GPU at all
(see [Getting Started](getting-started.md#trying-the-service-without-a-gpu)).

### Is my data private?

Your prompts and the model's completions are served entirely on the cluster and are not
sent to any outside provider. Your browser-chat history is stored in a private directory in
your home folder that other users cannot read. One caveat: coding tools can have their own
telemetry that is separate from the model service. The service disables that telemetry where
it controls the configuration, but you should confirm the settings in any client you install
yourself. A second caveat, opt-in: if you start browser chat with `AISESSION_TOOLS=1` (web
search, URL fetch, reference lookup — see below), those specific tool requests send your query
terms to services outside RCC. They are off unless you set that flag.

## Connecting and sharing

### How do I connect from my laptop?

Open an SSH tunnel from your laptop to the login node your session is running on, then point
your client at `http://localhost:<port>`. The exact tunnel command, with the right port and
login node filled in, is printed when you run `ai-session connect` and is shown in
[Getting Started](getting-started.md).

### Can my lab share one session?

Yes. The person who starts the session receives an access key. Share that key with your
labmates; each of them opens their own SSH tunnel to the same login node and uses the key as
their API key. Anyone without the key is refused. All usage is recorded under the person who
started the session, so coordinate within the group on who runs it.

### Which model should I use?

Use Qwen3.8-27B for code; Gemma-4-31B is a second coding option that is cheaper and
faster, and the trade-off between the two is set out on
[Coding Sessions](coding/overview.md#choosing-between-the-two-coding-models). Use the
Qwen2.5-72B general model for mixed prose-and-code work or when you specifically want the
largest general model, and Qwen3-4B for quick or small tasks. Qwen2.5-0.5B is served only by `--cpu` sessions,
for trying the service. For math and multi-step
planning, the Qwen3 thinking models reason before answering — the coding default
Qwen3.8-27B is itself a thinking model, as is the small Qwen3-4B. Both coding models accept
images alongside text; the rest are text-only.

Whichever you end up on, start small and scale up: get your prompts or agent setup working
against the small model first — it loads faster, spends less time waiting for free GPUs, and
holds a single GPU — then switch to a larger model without changing any client
configuration. If you need larger, ask; new models are staged on request. For a rough sense of
how these open models compare to closed "frontier" models, see the
[capability frame of reference](reference.md#rough-capability-frame-of-reference).

### Can the browser chat search the web or find papers?

Yes, opt-in. Start browser chat with `AISESSION_TOOLS=1 ai-session chat` to add three tools you
enable per conversation in Open WebUI: web search, URL fetch, and academic reference search
(arXiv, bioRxiv, medRxiv, PubMed, Semantic Scholar). All three work with any served model,
orchestrated by the UI. For the model to place the reference-tool calls itself, start a
tool-calling model with the `--agent` flag —
`AISESSION_TOOLS=1 ai-session chat --model qwen3.8_27B --agent`. These tools reach
outside RCC (see [Is my data private?](#is-my-data-private) and
[Getting Started](getting-started.md#web-search-and-reference-tools-opt-in)); they are off by
default.

## Coding agents, MCP, and building agents

### Which coding tool should I use?

aider is the dependable default for editing files: it needs no tool calling and no
configuration — start `ai-session code` and run plain `aider` (see [aider](coding/aider.md)).
opencode is supported for full tool-calling agents; it needs a session started with
`--agent`, and `eval "$(ai-session env)"` in your shell before you run `opencode` — no
`opencode.json` is needed (see [opencode and Cline](coding/opencode.md)). Claude Code runs
against the session with `ai-session claude` (see [Claude Code](coding/claude-code.md)).
Continue is the choice for in-editor use inside VS Code or JetBrains.

### My agent said it made a change, but nothing happened. Why?

Almost always because the session was started without `--agent`, so it accepts no tool
calls: the tool JSON comes back as ordinary text and the agent has nothing to act on. Stop
the session and restart it with `ai-session code --agent`. The other cause is a leftover
`AGENTS.md` tool-call workaround file in your repository root, which earlier versions of
these instructions asked for — delete it. See the
[troubleshooting page](troubleshooting.md).

### How do I add an MCP tool to my agent?

Add an `mcp` block to a project-local `opencode.json` in your working directory, not to your
personal configuration; `ai-session mcp config` prints a ready-to-paste block for the two
built-in tool servers (see [MCP Servers](coding/mcp.md)). Before you enable a server, read
the agent-responsibility guidance:
an MCP server runs with your full cluster permissions and can reach any file you can reach,
including a labmate's files through shared project directories.

### Can I build my own agent on these models?

Yes. Point any agent framework that speaks the standard OpenAI API format — for example
PydanticAI, LangGraph, smolagents, or the OpenAI Agents SDK — at the session URL, using
your session key as the API key. Every served model emits tool calls reliably, so pick on
capability and cost rather than on tool-calling support.

## Common problems

### Can I try the service without a GPU?

Yes. `ai-session chat --cpu --partition amd` (or `--partition caslake`) serves the small
Qwen2.5 0.5B model on a CPU-only node; the CPU partition is remembered separately from your
GPU partition. Measured on `amd`: the model is ready about 2 to 3 minutes after the job
starts, and a short chat reply returns in seconds. Only that model is served, and `--lora`
is refused. It is for trying the browser chat and checking that aider, opencode, or Claude
Code is wired up, not for real coding work. See
[Command Reference](reference.md#trying-the-service-without-a-gpu).

### My session sits in the queue and never starts.

The GPUs you requested may be busy. A session waits for cards to free up, and the start
command gives up if it waits too long. While it waits, the terminal prints
`waiting for a compute node` with the elapsed time, and `ai-session status` reports the same
stage. Try a smaller model (`ai-session fast`), or try
again later.

### My connection worked and then stopped.

If the login node was rebooted, or your SSH session dropped, the gateway — the connection
point on the login node — can stop while the GPU session keeps running. Check with
`ai-session status`; if the connection point is gone but a server is still listed, run
`ai-session stop` to release the GPUs and start again.

### My home directory filled up.

Browser-chat history is stored in your home directory, which has a smaller quota than
project space. Clear old conversations in the chat interface, or remove old files under
`$HOME/.ai-session/`.

### I forgot to stop my session.

An unused session holds its GPUs until its time limit expires (`--time`, default two
hours), and its whole held time is recorded. Always run
`ai-session stop` when you finish. If you routinely forget, ask RCC staff whether
the idle-session reaper is enabled, which warns and then ends sessions that have gone
quiet.
