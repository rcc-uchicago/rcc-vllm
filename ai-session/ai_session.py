#!/usr/bin/env python3
"""ai-session CLI: start / status / end.

Single-user-per-session vLLM serving on RCC with SU metering.

  ai_session.py start  --model qwen2.5_72B --tp 4 --constraint A100 [--wait]
  ai_session.py status [--jobid N]
  ai_session.py end    [--jobid N] [--usage-jsonl client_usage.jsonl]

`start` submits launch_ai_session.sh (job-name 'model_key:port'), records a
session file, and prints the endpoint URL once RUNNING. `end` does a final
/metrics scrape, computes the SU charge (token term + exclusive-node floor),
writes a usage log, and scancels the job.

--account and --partition are required (no default); they are unique per
user/PI and come from the flag or the ACCOUNT/PARTITION environment variables.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BILLING = os.path.join(os.path.dirname(_HERE), "billing")
for p in (_HERE, _BILLING):
    if p not in sys.path:
        sys.path.insert(0, p)

import gateway  # noqa: E402
import metering  # noqa: E402
import preflight_estimate as preflight  # noqa: E402
import server  # noqa: E402
import su_formula as su  # noqa: E402

# Writable state (session files, usage/billing logs, gateway pointer) lives under
# AISESSION_STATE_DIR when set, so multiple rcc-staff can share this one read-only
# code/venv/models install without clobbering each other's upstream.json or logs.
# Unset -> next to the code (single-tenant default; mehta5's original layout).
# Must match gateway.py's _STATE and launch_ai_session.sh's STATE_BASE.
_STATE = os.environ.get("AISESSION_STATE_DIR") or _HERE
SESSION_DIR = os.path.join(_STATE, "logs", "sessions")
USAGE_DIR = os.path.join(_STATE, "logs", "usage")
GATEWAY_DIR = os.path.join(_STATE, "logs", "gateway")
LICENSE_ACK_DIR = os.path.join(_STATE, "logs", "licenses")  # per-user license acceptances
LAUNCHER = os.path.join(_HERE, "launch_ai_session.sh")  # code, not state -> always _HERE

# Models whose licenses impose obligations when you SERVE them to others (as this
# service does). Any user may serve one, but only after recording a per-user
# acknowledgment of the license (see _require_license_ack) -- this fires on every
# start of a gated key, regardless of the served-set/--force path.
# The Apache-2.0 models (coder_32B, qwen3_4b, 0.5B) are permissive and NOT gated;
# only Llama 3.1 (Community License + Acceptable Use Policy) is. The 72B Qwen
# community-license model is in PHASE1_SERVED and carries attribution/NOTICE
# obligations documented in docs/licenses.md, but is not force-gated here.
_LICENSE_GATED = {
    "llama3.1_70B": {
        "name": "Llama 3.1 Community License + Acceptable Use Policy",
        "files": ("LICENSE", "USE_POLICY.md"),
        "env": "ACCEPT_LLAMA_LICENSE",
    },
}


# --------------------------------------------------------------------------- #
# identity: derive the username from the REAL uid, never $USER/$LOGNAME (which a
# caller can set to anyone). Every receipt, session file, license-ack, and the
# central billing record is attributed with this, so it must not be spoofable.
# The real GPU charge is enforced by Slurm against the job's --account regardless;
# this keeps the service's own attribution honest too.
# --------------------------------------------------------------------------- #
def _real_user() -> str:
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except (KeyError, OSError):
        return os.environ.get("USER") or os.environ.get("LOGNAME") or "unknown"


# --------------------------------------------------------------------------- #
# license acknowledgment gate (restrictively-licensed --force models)
# --------------------------------------------------------------------------- #
def _license_ack_path(model_key: str) -> str:
    user = _real_user()
    return os.path.join(LICENSE_ACK_DIR, f"{user}_{model_key}.accepted")


def _require_license_ack(model_key: str) -> None:
    """Refuse to serve a license-gated model until the user has recorded acceptance.

    Acceptance is per user and persistent: once ``ACCEPT_LLAMA_LICENSE=1`` writes
    the record, later starts reuse it (no env needed). This is deliberately the
    non-interactive env form so batch scripts work; the refusal message names the
    env to set. Called on every start of a key in ``_LICENSE_GATED``.
    """
    info = _LICENSE_GATED[model_key]
    lic_path = os.path.join(server.model_path(model_key), info["files"][0])
    ack_path = _license_ack_path(model_key)
    if os.path.exists(ack_path):
        return  # already accepted in a prior run
    if os.environ.get(info["env"]) == "1":
        _write_license_ack(model_key, lic_path, ack_path, info)
        print(f"[start] recorded {info['name']} acceptance -> {ack_path}")
        return
    on_disk = ", ".join(
        os.path.join(server.model_path(model_key), f) for f in info["files"]
    )
    raise SystemExit(
        f"{model_key!r} is served under the {info['name']}.\n"
        f"  On-disk license: {on_disk}\n"
        f"  Serving it to others carries obligations (see docs/licenses.md).\n"
        f"  To accept and proceed non-interactively, set {info['env']}=1, e.g.:\n"
        f"      {info['env']}=1 ai-session chat --model {model_key}\n"
        f"  This writes a one-time acceptance record to {ack_path};\n"
        f"  it is required only the first time -- later starts reuse it."
    )


def _write_license_ack(model_key: str, lic_path: str, ack_path: str, info: dict) -> None:
    os.makedirs(LICENSE_ACK_DIR, exist_ok=True)
    user = _real_user()
    record = {
        "user": user,
        "model_key": model_key,
        "license": info["name"],
        "accepted_license_at": lic_path,
        "acceptance": f"{user} accepted the {info['name']} at {lic_path}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "env_ack": f"{info['env']}=1",
    }
    with open(ack_path, "w") as f:
        json.dump(record, f, indent=2)


# --------------------------------------------------------------------------- #
# session-file helpers
# --------------------------------------------------------------------------- #
def _session_path(jobid: str) -> str:
    user = _real_user()
    return os.path.join(SESSION_DIR, f"{user}_{jobid}.json")


def _save_session(session: dict) -> str:
    os.makedirs(SESSION_DIR, exist_ok=True)
    path = _session_path(session["jobid"])
    with open(path, "w") as f:
        json.dump(session, f, indent=2)
    return path


def _load_session(jobid: str = None) -> dict:
    os.makedirs(SESSION_DIR, exist_ok=True)
    if jobid:
        path = _session_path(jobid)
        if not os.path.exists(path):
            raise SystemExit(f"no session file for jobid {jobid} ({path})")
        with open(path) as f:
            return json.load(f)
    # latest by mtime
    files = [os.path.join(SESSION_DIR, f) for f in os.listdir(SESSION_DIR) if f.endswith(".json")]
    if not files:
        raise SystemExit("no sessions found; run `ai_session.py start` first")
    latest = max(files, key=os.path.getmtime)
    with open(latest) as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
# squeue helpers
# --------------------------------------------------------------------------- #
def _squeue_row(jobid: str):
    """Return (state, node) for a jobid, or (None, None)."""
    r = subprocess.run(
        ["squeue", "-j", str(jobid), "-h", "-o", "%T|%N"],
        capture_output=True, text=True,
    )
    line = r.stdout.strip()
    if not line:
        return None, None
    state, _, node = line.partition("|")
    return state.strip() or None, (node.strip() or None)


def _clear_gateway_if_ours(jobid: str) -> None:
    """Clear the gateway upstream only if it currently points at this job."""
    up = gateway._Upstream().get()
    if up and str(up.get("jobid")) == str(jobid):
        gateway.clear_upstream()
        print("[end] gateway upstream cleared (no active backend).")


def _existing_ai_sessions() -> list:
    """This user's active ai-session jobs, as ``[(jobid, model_key, state)]``.

    ``squeue --me`` lists only the caller's own non-terminal jobs (PENDING /
    CONFIGURING / RUNNING / ...), so this NEVER sees another user's work. A job is
    an ai-session job when its name is ``<model_key>:<port>`` with model_key in
    MODEL_REGISTRY -- the same convention server.py discovery uses.
    """
    r = subprocess.run(
        ["squeue", "--me", "-h", "-o", "%i|%j|%T"],
        capture_output=True, text=True,
    )
    found = []
    for line in r.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        jid, jobname, state = parts[0], parts[1], parts[2]
        model_key = jobname.split(":", 1)[0]
        if model_key in server.MODEL_REGISTRY:
            found.append((jid, model_key, state))
    return found


# --------------------------------------------------------------------------- #
# start
# --------------------------------------------------------------------------- #
def cmd_start(args) -> int:
    if args.model not in server.MODEL_REGISTRY:
        raise SystemExit(f"unknown model {args.model!r}; registered: {sorted(server.MODEL_REGISTRY)}")
    if args.cpu and args.model not in server.CPU_SERVED:
        raise SystemExit(
            f"--cpu serves only {sorted(server.CPU_SERVED)}; {args.model!r} needs a GPU session."
        )
    if args.model not in server.PHASE1_SERVED and not args.force:
        raise SystemExit(
            f"{args.model!r} is not in PHASE1_SERVED {sorted(server.PHASE1_SERVED)}; "
            f"pass --force to serve it anyway."
        )
    # License acknowledgment gate: serving a restrictively-licensed model (Llama 3.1)
    # is refused until the user has recorded acceptance. Any user may serve it, but the
    # first start must set ACCEPT_LLAMA_LICENSE=1. Runs BEFORE any GPU job is submitted,
    # and independently of the served-set/--force path above.
    if args.model in _LICENSE_GATED:
        _require_license_ack(args.model)

    # item 16: one running session per user. A GPU reservation is floor-billed for
    # its whole life, so a second accidental `start` (a re-run, or a coding wrapper
    # launched on top of a browser demo) silently doubles the charge. Refuse if this
    # user already has an active ai-session job unless --allow-multiple is given.
    # Runs BEFORE any GPU job is submitted below.
    if not args.allow_multiple:
        existing = _existing_ai_sessions()
        if existing:
            listed = "; ".join(f"jobid={j} {m} ({stt})" for j, m, stt in existing)
            raise SystemExit(
                f"you already have an active ai-session job: {listed}.\n"
                "  Each reservation is billed for the whole node while it is up. End it\n"
                "  first with `ai_session.py end` (or the wrapper `down`), or pass\n"
                "  --allow-multiple to intentionally run more than one at once."
            )
    model_path = server.model_path(args.model)

    if not args.account or not args.partition:
        raise SystemExit(
            "ai_session start: --account and --partition are required (they are\n"
            "  unique to you and your PI; there is no default). Pass them, or set\n"
            "  ACCOUNT and PARTITION in the environment. The `ai-session` command\n"
            "  does this for you and remembers them after the first run."
        )

    env = dict(os.environ)
    env.update({
        "MODEL_KEY": args.model,
        "MODEL_PATH": model_path,
        "TP": str(args.tp),
        "CONSTRAINT": args.constraint,
        "GRES": args.gres or f"gpu:{args.tp}",
        "ACCOUNT": args.account,
        "PARTITION": args.partition,
        "MAX_MODEL_LEN": str(args.max_model_len),
        "GPU_MEM_UTIL": str(args.gpu_mem_util),
        "ENFORCE_EAGER": "1" if args.enforce_eager else "0",
        "AGENT_CLIENT": "1" if args.agent_client else "0",
        # The launcher's CPU switch: no gres/constraint, the vllm-cpu env.
        "DEVICE": "cpu" if args.cpu else "gpu",
    })
    # Walltime. Respect a caller-exported TIME_LIMIT (the wrappers' TIME= knob sets
    # it) so it is NOT clobbered; only fall back to --time (default 02:00:00) when the
    # caller did not export one. setdefault gives exactly that precedence: existing
    # env value wins, else --time. (The previous code overwrote TIME_LIMIT
    # unconditionally, pinning every wrapper session to 02:00:00.)
    env.setdefault("TIME_LIMIT", args.time)

    # User-facing usage is reported as tokens consumed per job (no SU figures; the
    # wrappers say so before start). The SU math still runs at `end` and is kept in
    # the summary JSON + ledger.

    proc = subprocess.run(["bash", LAUNCHER], env=env, capture_output=True, text=True)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(f"launcher failed (rc={proc.returncode})")
    json_line = [ln for ln in proc.stdout.strip().splitlines() if ln.strip().startswith("{")]
    if not json_line:
        raise SystemExit(f"launcher produced no JSON line; stdout was:\n{proc.stdout}")
    launch = json.loads(json_line[-1])
    # The backend API key protects the vLLM /v1 endpoint. Pop it BEFORE building
    # the session dict so it never lands in the group-readable on-disk session
    # file; it is only handed to the gateway (upstream.json, 0600) below.
    backend_key = launch.pop("backend_key", None)

    session = {
        **launch,
        "user": _real_user(),
        "submit_epoch": time.time(),
        "node": None,
        "start_epoch": None,
        "m_before": None,
        "status": "submitted",
    }
    path = _save_session(session)
    print(f"[start] submitted {args.model} jobid={launch['jobid']} port={launch['port']}")
    print(f"[start] session file: {path}")

    if args.wait:
        # The job is submitted but not yet READY, and the wrapper's teardown trap
        # is not armed until this call returns. Any early exit here -- ready-timeout,
        # Ctrl-C, an SSH drop (SIGHUP), SIGTERM, or an error -- would otherwise leave
        # the reservation RUNNING and floor-billing as an orphan. Guard the wait and
        # scancel EXACTLY the job we just submitted (launch['jobid']) on any such
        # exit: no pre-existing-session ambiguity, since we only touch our own job.
        import signal
        def _abort_bringup(signum, _frame):
            raise SystemExit(f"signal {signum} received while bringing up job {session['jobid']}")
        _prev_handlers = {sig: signal.getsignal(sig)
                          for sig in (signal.SIGTERM, signal.SIGHUP)}
        for sig in _prev_handlers:
            signal.signal(sig, _abort_bringup)
        try:
            _wait_running_and_ready(session, args.ready_timeout, backend_key)
        except BaseException as exc:
            jobid = session["jobid"]
            print(f"[start] bring-up aborted for job {jobid} "
                  f"({type(exc).__name__}); scancel to avoid an orphaned, "
                  f"floor-billed reservation.", file=sys.stderr)
            subprocess.run(["scancel", str(jobid)], check=False)
            session["status"] = "aborted"
            _save_session(session)
            _clear_gateway_if_ours(jobid)
            raise
        finally:
            for sig, handler in _prev_handlers.items():
                signal.signal(sig, handler)
    else:
        print("[start] not waiting; run `ai_session.py status` to see when it is ready.")
    return 0


# Bring-up progress. vLLM exposes no load-progress API, so the stage is read from the
# server's own log: each marker is the first line vLLM prints once that stage is done
# (same strings on the CPU and GPU builds; checked on vLLM 0.10.2 and 0.26.0 logs).
# Ordered: the LAST marker present decides the stage shown.
_LOAD_STAGES = (
    ("Initializing a V1 LLM engine", "loading the model weights"),
    ("Loading weights took", "compiling and warming up the model"),
    ("init engine", "starting the API server"),
    ("Available routes are", "finishing start-up"),
)
PROGRESS_FILE = os.path.join(_STATE, "run", "progress.json")


def _load_stage(server_log: str | None) -> str:
    """Human-readable bring-up stage from the tail of the vLLM server log."""
    stage = "starting vLLM"
    if not server_log:
        return stage
    try:
        with open(server_log, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 512 * 1024))
            tail = f.read().decode("utf-8", "replace")
    except OSError:
        return stage
    for marker, label in _LOAD_STAGES:
        if marker in tail:
            stage = label
    return stage


def write_progress(state: str, message: str, **extra) -> None:
    """Record the bring-up state for `ai-session status` (best-effort, never raises).

    state: 'queued' | 'loading' | 'model_ready' | 'ready' | 'failed'
    """
    rec = {"state": state, "message": message, "updated": time.time(), **extra}
    try:
        os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
        tmp = PROGRESS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(rec, f)
        os.replace(tmp, PROGRESS_FILE)
    except OSError:
        pass


def _mmss(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _wait_running_and_ready(session: dict, ready_timeout: int, backend_key: str = None) -> None:
    jobid, port = session["jobid"], session["port"]
    t0 = time.time()
    # AISESSION_KIND (set by `ai-session chat|fast|code`) picks the wording: a
    # coding session has no web page -- its clients are opencode / aider / Continue.
    if os.environ.get("AISESSION_KIND") == "code":
        banner = (
            "  vLLM is starting -- PLEASE WAIT. The session is NOT ready yet.",
            "  Do not start opencode or aider (or open an SSH tunnel) until",
            "  you see the READY box with the connection settings. Progress",
            "  is shown below; from another terminal, `ai-session status`",
            "  shows it too.",
        )
    else:
        banner = (
            "  vLLM is starting -- PLEASE WAIT. The web page is NOT ready yet.",
            "  Do not open the SSH tunnel or the browser until you see the",
            "  READY box with the tunnel command. Progress is shown below;",
            "  from another terminal, `ai-session status` shows it too.",
        )
    print("")
    print("=" * 66)
    for line in banner:
        print(line)
    print("=" * 66)
    print(f"[start] job {jobid}: waiting for a compute node (timeout {ready_timeout}s)...")
    write_progress("queued", "waiting for a compute node", jobid=jobid)
    deadline = time.time() + ready_timeout
    node = None
    while time.time() < deadline:
        state, node = _squeue_row(jobid)
        if state is None:
            write_progress("failed", "the job left the queue before it started", jobid=jobid)
            raise SystemExit(f"job {jobid} disappeared from the queue before becoming ready")
        if state == "RUNNING" and node:
            break
        print(f"   [{_mmss(time.time() - t0)}] waiting for a compute node (job {state}) ...")
        time.sleep(15)
    session["node"] = node
    print(f"[start] job {jobid} is running on {node}; vLLM is loading the model.")

    # Poll /metrics (it answers only once the engine is up) and report the load stage
    # from the server log. The expected scrape failures go to the session's .out log,
    # not the console.
    last_stage = None
    while time.time() < deadline:
        # A job that dies while loading (engine init failure) leaves the queue; stop
        # waiting at once instead of polling a dead port until ready_timeout.
        state, _ = _squeue_row(jobid)
        if state is None:
            write_progress("failed", "the model server stopped while loading", jobid=jobid,
                           server_log=session.get("server_log"))
            raise SystemExit(f"job {jobid} left the queue while loading the model; "
                             f"see {session.get('server_log')} (and its .err)")
        m = metering.scrape_metrics(node, port, quiet=True, log_path=session.get("server_log"))
        if m:  # /metrics responds once the engine is up
            session["start_epoch"] = time.time()
            session["m_before"] = m
            session["status"] = "running"
            _save_session(session)
            url = f"http://{node}:{port}/v1"
            # Publish this backend to the gateway so its fixed URL now points here.
            # backend_key travels here (upstream.json is written 0600) so the gateway
            # can authenticate to the key-gated /v1; it is never saved to the session.
            # Advertise the SERVED name: clients send it as the request's model, and a
            # smoke run serves under a bench-* name that differs from the registry key.
            served = session.get("served_model_name") or session["model_key"]
            gateway.write_upstream(f"http://{node}:{port}", model_key=served,
                                   jobid=session["jobid"], backend_key=backend_key)
            write_progress("model_ready", "model loaded; starting the gateway and clients",
                           jobid=jobid, node=node)
            print(f"[start] model loaded after {_mmss(time.time() - t0)}. Direct endpoint: {url}")
            print(f"[start]   model={session['model_key']}  (direct /v1 needs the backend key -- use the gateway URL)")
            print("[start] gateway updated -> clients on the gateway URL now reach this session.")
            return
        stage = _load_stage(session.get("server_log"))
        write_progress("loading", stage, jobid=jobid, node=node, since=t0)
        if stage != last_stage:
            print(f"   [{_mmss(time.time() - t0)}] {stage} ...")
            last_stage = stage
        else:
            print(f"   [{_mmss(time.time() - t0)}] still {stage} -- please wait")
        time.sleep(20)
    write_progress("failed", f"the model did not load within {ready_timeout}s", jobid=jobid)
    raise SystemExit(f"job {jobid} did not become ready within {ready_timeout}s")


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def cmd_status(args) -> int:
    session = _load_session(args.jobid)
    jobid, port = session["jobid"], session["port"]
    state, node = _squeue_row(jobid)
    node = node or session.get("node")
    print(f"jobid={jobid} model={session['model_key']} state={state or 'GONE'} node={node or '-'} port={port}")
    if state == "RUNNING" and node:
        url = f"http://{node}:{port}/v1"
        print(f"endpoint: {url}  (model={session['model_key']})")
        m = metering.scrape_metrics(node, port)
        if m:
            print(f"/metrics: prompt_tokens={int(m.get('vllm:prompt_tokens_total',0))} "
                  f"generation_tokens={int(m.get('vllm:generation_tokens_total',0))} "
                  f"success_requests={int(m.get('vllm:request_success_total',0))}")
        else:
            print("/metrics: not reachable yet (model may still be loading)")
    return 0


# --------------------------------------------------------------------------- #
# end
# --------------------------------------------------------------------------- #
def cmd_end(args) -> int:
    session = _load_session(args.jobid)
    jobid, port = session["jobid"], session["port"]
    session["end_epoch"] = time.time()  # set early so the gateway-usage window is correct
    state, node = _squeue_row(jobid)
    node = node or session.get("node")

    # Stop routing new traffic to this backend before we meter + tear down.
    _clear_gateway_if_ours(jobid)

    # final /metrics scrape (best-effort)
    m_after = metering.scrape_metrics(node, port) if node else {}

    # Running engine version, for the rate-table version guard: the matched rate
    # record is only valid for the vLLM version it was measured under. Best-effort
    # (the engine is still up until scancel below); None -> guard fails open.
    running_version = metering.scrape_version(node, port) if node else None

    # reserved wall time for the floor
    rwh = server.reserved_wall_hours(jobid, session.get("start_epoch") or session.get("submit_epoch"))
    if rwh is None:
        rwh = 0.0
        print("[end] WARNING: could not determine reserved wall time; floor uses 0h.", file=sys.stderr)

    if session.get("device") == "cpu":
        # No GPU was reserved, so there is no GPU-SU to bill: the tier/rate lookup
        # below would KeyError on tier 'cpu' and abort `end` BEFORE the scancel.
        return _end_cpu_session(args, session, state, rwh)

    # GPU count N: prefer actual allocation, else requested gres. Detect whole-node.
    n_alloc = server.resolve_job_gpus(jobid)
    n_billed = args.n_gpus or n_alloc or session.get("n_gpus_requested") or session["tp"]
    if n_alloc and n_alloc > session["tp"]:
        print(f"[end] NOTE: job holds {n_alloc} GPUs but TP={session['tp']} "
              f"(whole-node reservation) -> billing N={n_billed}.", file=sys.stderr)

    # GPU tier: prefer resolved node feature, else the launch constraint.
    tier = server.resolve_node_tier(node) or session.get("tier_requested")

    policy = su.load_policy(args.policy)
    rate_table = su.load_rate_table(args.rate_table)

    # Token source priority: explicit --usage-jsonl > gateway usage log for this
    # session window > /metrics delta (handled inside compute_session_su).
    if args.usage_jsonl:
        requests = metering.read_usage_jsonl(args.usage_jsonl)
    else:
        requests = metering.read_gateway_usage(
            GATEWAY_DIR,
            session.get("start_epoch") or session.get("submit_epoch"),
            session.get("end_epoch") or time.time(),
        ) or None
        if requests:
            print(f"[end] using gateway usage log ({len(requests)} requests) as the billing source.")

    summary = metering.compute_session_su(
        model_key=session["model_key"],
        tier=tier,
        served_tp=session["tp"],
        n_gpus_billed=int(n_billed),
        reserved_wall_hours=rwh,
        policy=policy,
        rate_table=rate_table,
        requests=requests,
        m_before=session.get("m_before"),
        m_after=m_after,
        running_version=running_version,
    )

    session["m_after"] = m_after
    session["status"] = "ended"
    _save_session(session)

    paths = metering.write_usage_log(session, requests or [], summary, USAGE_DIR)

    # Also record this charge to the central staff-only accounting ledger
    # (in addition to the per-user summary above). Best-effort: a missing or
    # unwritable ledger must not break `end`, so this never raises.
    central = metering.write_central_billing_record(session, summary)
    if central:
        print(f"[end] recorded to central ledger: {central}")

    # teardown
    if state and not args.no_cancel:
        subprocess.run(["scancel", str(jobid)])
        print(f"[end] scancel {jobid}")
    elif args.no_cancel:
        print(f"[end] --no-cancel: leaving job {jobid} running")

    _print_summary(summary, paths)
    return 0


def _end_cpu_session(args, session: dict, state, rwh: float) -> int:
    """Finish a `--cpu` session: record the tokens the job consumed, then scancel.

    No SU figure is computed for a CPU session; the receipt is token usage only.
    """
    jobid = session["jobid"]
    requests = metering.read_gateway_usage(
        GATEWAY_DIR,
        session.get("start_epoch") or session.get("submit_epoch"),
        session.get("end_epoch") or time.time(),
    ) or []
    tin = sum(int(r.get("prompt_tokens") or 0) for r in requests)
    tout = sum(int(r.get("completion_tokens") or 0) for r in requests)
    summary = {
        "model_key": session["model_key"], "gpu_tier": "cpu", "served_tp": session["tp"],
        "n_gpus_billed": 0, "w_gpu": None, "reserved_wall_hours": round(rwh, 4),
        "token_source": "gateway" if requests else "none",
        "total_input_tokens": tin, "total_output_tokens": tout,
        "n_requests_billed": len(requests), "rated": False, "rate_record_found": False,
        "engine_version": None, "rated_version": None, "version_mismatch": False,
        "prefill_tps": None, "decode_tps": None,
        "token_su": None, "floor_su": None, "billed_su": None,
        "basis": "cpu session: token usage only",
        "currency": None, "crosscheck": None,
    }
    session["status"] = "ended"
    _save_session(session)
    paths = metering.write_usage_log(session, requests, summary, USAGE_DIR)
    if state and not args.no_cancel:
        subprocess.run(["scancel", str(jobid)])
        print(f"[end] scancel {jobid}")
    elif args.no_cancel:
        print(f"[end] --no-cancel: leaving job {jobid} running")
    _print_summary(summary, paths)
    return 0


def _print_summary(s: dict, paths: dict) -> None:
    # Users see tokens consumed per job only. The SU fields stay in the summary
    # JSON (and the central ledger) for staff, but are not printed.
    where = "cpu" if s.get("gpu_tier") == "cpu" else f"{s.get('n_gpus_billed')} x {s.get('gpu_tier')} GPU"
    print("\n=== ai-session usage ===")
    print(f"  model         : {s['model_key']}  ({where})")
    print(f"  tokens        : in={s['total_input_tokens']} out={s['total_output_tokens']} "
          f"total={s['total_input_tokens'] + s['total_output_tokens']} "
          f"(requests={s['n_requests_billed']}, source={s['token_source']})")
    print(f"  usage summary : {paths['summary']}")
    if paths.get("jsonl"):
        print(f"  per-request   : {paths['jsonl']}")


def _print_su_summary(s: dict, paths: dict) -> None:
    """The former SU receipt -- kept for staff tooling; not printed to users."""
    print("\n=== ai-session billing summary ===")
    print(f"  model/tier/TP : {s['model_key']} / {s['gpu_tier']} / TP={s['served_tp']}")
    print(f"  GPUs billed N : {s['n_gpus_billed']}   w_gpu={s['w_gpu']}")
    print(f"  reserved      : {s['reserved_wall_hours']:.4f} h")
    print(f"  tokens        : in={s['total_input_tokens']} out={s['total_output_tokens']} "
          f"(source={s['token_source']}, requests={s['n_requests_billed']})")
    if s["rated"]:
        print(f"  throughput    : prefill={s['prefill_tps']} tok/s  decode={s['decode_tps']} tok/s")
        print(f"  token SU      : {s['token_su']:.6f}")
    elif s.get("version_mismatch"):
        print(f"  token SU      : UNRATED (engine vLLM {s.get('engine_version')} != rated "
              f"{s.get('rated_version')} -- re-benchmark this tier; see README 'Upgrading vLLM')")
    else:
        print("  token SU      : UNRATED (no rate_table record -- run bench_billing.sbatch)")
    print(f"  floor SU      : {s['floor_su']:.4f}")
    bs = s["billed_su"]
    print(f"  BILLED SU     : {bs:.4f}" if bs is not None else "  BILLED SU     : (undetermined)")
    print(f"  basis         : {s['basis']}")
    if s.get("crosscheck"):
        c = s["crosscheck"]
        print(f"  /metrics check: reconciled={c['reconciled']} "
              f"(in {c['per_request_input_tokens']} vs {int(c['metrics_input_tokens_delta'])}, "
              f"out {c['per_request_output_tokens']} vs {int(c['metrics_output_tokens_delta'])})")
    print(f"  usage summary : {paths['summary']}")
    if paths.get("jsonl"):
        print(f"  per-request   : {paths['jsonl']}")


# --------------------------------------------------------------------------- #
# connect -- print client setup for the current session
# --------------------------------------------------------------------------- #
def cmd_connect(args) -> int:
    session = _load_session(args.jobid)
    model = session["model_key"]
    state, node = _squeue_row(session["jobid"])
    node = node or session.get("node")
    port = session["port"]
    # Short node name for display; the tunnel line appends the external DNS suffix
    # so it matches the single-hop form every doc example uses (uname gives a bare
    # or internal name, which is not what a laptop can ssh to).
    gw_host = (args.gateway_host or os.uname().nodename).split(".")[0]
    # Default port must MATCH the wrappers' UID-derived scheme (8400 + uid % 90),
    # else `connect` prints a URL no gateway is listening on. Precedence:
    # explicit --gateway-port > exported GW_PORT > the derived per-user default.
    gw_port = args.gateway_port or int(os.environ.get("GW_PORT") or (8400 + os.getuid() % 90))
    gw_url_oncluster = f"http://{gw_host}:{gw_port}/v1"
    gw_url_tunnel = f"http://localhost:{gw_port}/v1"
    # A live session mints a per-session access key at logs/gateway/session_key. The
    # gateway REQUIRES it; you share it with your lab and everyone's usage bills to
    # you (the starter). An explicit --gateway-key overrides. If no key file exists
    # the session is keyless (dev only) and any api_key string works.
    keyfile = os.path.join(GATEWAY_DIR, "session_key")
    file_key = None
    if os.path.exists(keyfile):
        try:
            with open(keyfile) as f:
                file_key = f.read().strip() or None
        except OSError:
            file_key = None
    has_key = bool(args.gateway_key or file_key)
    key = args.gateway_key or file_key or "ai-session"
    starter = _real_user()

    print(f"\n=== connect: session {session['jobid']} ({model}, state={state or 'GONE'}) ===")
    if has_key:
        print(f"\nSESSION ACCESS KEY:  {key}")
        print("  The gateway REQUIRES this key. Share it with your lab so they can use THIS")
        print(f"  session over their OWN tunnel to :{gw_port}; each member sets it as the OpenAI")
        print(f"  API key in their client. ALL of their usage bills to you ({starter}), the starter.")
        print("  Without the key the gateway refuses every request (401).")
    else:
        print("\nSESSION ACCESS KEY:  (none -- this gateway is keyless; any api_key string works)")
    if node:
        print(f"direct (changes each session): http://{node}:{port}/v1")
    print("\n--- RECOMMENDED: go through the gateway (stable URL across sessions) ---")
    print(f"1) Make sure the gateway is running on {gw_host}:")
    print(f"     python {os.path.join(_HERE, 'gateway.py')} --port {gw_port}")
    print("2) If your client runs on your LAPTOP, open the tunnel (one login, -f backgrounds it):")
    print(f"     ssh -N -f -L {gw_port}:localhost:{gw_port} "
          f"{os.environ.get('USER', 'you')}@{gw_host}.rcc.uchicago.edu")
    print("   (on a cluster login node you can skip the tunnel and use the on-cluster URL)")
    print("\nClient connection settings:")
    print(f"   base_url (laptop, via tunnel) : {gw_url_tunnel}")
    print(f"   base_url (on cluster)         : {gw_url_oncluster}")
    print(f"   model                         : {model}")
    print(f"   api_key                       : {key}")

    print("\n--- shell setup shared by the clients below (one command) ---")
    print("   eval \"$(ai-session env)\"   # sets AISESSION_BASE_URL / AISESSION_API_KEY / AISESSION_MODEL")

    print("\n--- Open WebUI (general chat / docs; needs no tool-calling) ---")
    print("   # one-time, in a SEPARATE env on a login node (NOT vllm-probe):")
    print("   #   python -m venv ~/openwebui-env && source ~/openwebui-env/bin/activate && pip install open-webui")
    print("   OPENAI_API_BASE_URL=$AISESSION_BASE_URL OPENAI_API_KEY=$AISESSION_API_KEY open-webui serve --port 3000")
    print("   # then browse http://localhost:3000 ; the model list will show:", model)

    meta = os.path.join(_HERE, "aider_model_metadata.json")
    print("\n--- aider (coding DEFAULT; robust with local models, no server-side tools needed) ---")
    print("   # --analytics-disable stops aider's own telemetry (independent of the model")
    print("   # traffic, which never leaves RCC):")
    print("   OPENAI_API_BASE=$AISESSION_BASE_URL OPENAI_API_KEY=$AISESSION_API_KEY \\")
    print(f"     aider --model openai/{model} --weak-model openai/{model} \\")
    print(f"       --model-metadata-file {meta} --edit-format diff --analytics-disable")

    print("\n--- Continue.dev (coding in VS Code / JetBrains) -- ~/.continue/config.yaml ---")
    print("   models:")
    print(f"     - name: {model} (RCC)")
    print("       provider: openai")
    print(f"       model: {model}")
    print(f"       apiBase: {gw_url_tunnel}")
    print(f"       apiKey: {key}")
    print("       roles: [chat, edit, apply]")

    print("\n--- opencode (autonomous agent; supported, verified 2026-07-03 -- needs --agent-client) ---")
    print("   module load opencode")
    print("   eval \"$(ai-session env)\"     # sets OPENCODE_CONFIG_CONTENT: URL, key, model")
    print("   opencode                       # no opencode.json needed; overrides a repo's own")
    print(f"\nFull end-user coding guide: {os.path.join(_HERE, 'CODING_AGENTS.md')}")
    print("\nNOTE: on an exclusively-reserved node you are billed for the whole reservation")
    print("      (the floor) whether busy or idle -- run `ai_session.py end` as soon as you stop.")
    return 0


# --------------------------------------------------------------------------- #
# argparse
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("start", help="launch a session")
    s.add_argument("--model", required=True, help=f"one of {sorted(server.MODEL_REGISTRY)}")
    s.add_argument("--tp", type=int, default=4)
    s.add_argument("--constraint", default="A100", help="GPU tier constraint (A100/H200/H100/L40S/A40)")
    s.add_argument("--gres", default=None, help="defaults to gpu:<tp>")
    # No hard-coded defaults: account and partition are unique per user/PI and
    # must be supplied (via flag or the ACCOUNT/PARTITION env vars the wrappers
    # export). A silent default would bill the wrong Slurm account.
    s.add_argument("--account", default=os.environ.get("ACCOUNT") or None)
    s.add_argument("--partition", default=os.environ.get("PARTITION") or None)
    s.add_argument("--time", default="02:00:00")
    s.add_argument("--max-model-len", type=int, default=8192)
    s.add_argument("--gpu-mem-util", type=float, default=0.90)
    s.add_argument("--enforce-eager", action="store_true",
                   help="disable torch.compile (keep in sync with the benchmark for that tier)")
    s.add_argument("--agent-client", action="store_true",
                   help="enable server-side tool-calling + larger context for agent clients "
                        "(opencode/Cline); not needed for Open WebUI or aider")
    s.add_argument("--wait", action="store_true", help="block until the endpoint is ready")
    s.add_argument("--ready-timeout", type=int, default=1800)
    s.add_argument("--force", action="store_true", help="serve a model outside PHASE1_SERVED")
    s.add_argument("--cpu", action="store_true",
                   help=f"serve on a CPU-only partition (no GPU; usage reported as tokens); only {sorted(server.CPU_SERVED)}")
    s.add_argument("--allow-multiple", action="store_true",
                   help="allow starting a second session while you already have one "
                        "running (default: refuse -- each reservation is floor-billed)")
    s.set_defaults(func=cmd_start)

    st = sub.add_parser("status", help="show session state + endpoint")
    st.add_argument("--jobid", default=None)
    st.set_defaults(func=cmd_status)

    c = sub.add_parser("connect", help="print client setup (gateway URL, tunnel, Open WebUI / aider / opencode)")
    c.add_argument("--jobid", default=None)
    c.add_argument("--gateway-host", default=None, help="host running gateway.py (default: this host)")
    c.add_argument("--gateway-port", type=int, default=None,
                   help="gateway port (default: $GW_PORT, else the per-user derived port)")
    c.add_argument("--gateway-key", default=None, help="must match AISESSION_GATEWAY_KEY if the gateway requires one")
    c.set_defaults(func=cmd_connect)

    e = sub.add_parser("end", help="meter, write usage log, scancel")
    e.add_argument("--jobid", default=None)
    e.add_argument("--usage-jsonl", default=None,
                   help="client-written per-request usage JSONL (authoritative); "
                        "omit to bill from the /metrics session delta")
    e.add_argument("--n-gpus", type=int, default=None, help="override billed GPU count N")
    e.add_argument("--policy", default=su.DEFAULT_POLICY_PATH)
    e.add_argument("--rate-table", default=su.DEFAULT_RATE_TABLE_PATH)
    e.add_argument("--no-cancel", action="store_true", help="do not scancel (debug)")
    e.set_defaults(func=cmd_end)
    return p


def main() -> int:
    # The wrappers pipe this through `tee`; without line buffering the progress lines
    # sit in Python's buffer and the terminal looks frozen until start-up finishes.
    sys.stdout.reconfigure(line_buffering=True)
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
