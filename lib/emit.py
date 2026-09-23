#!/usr/bin/env python3
"""Driver for /forge:emit — turn a .forge.org.yaml into an org-owned harness.

Computes the org-tier bindings from the config, then calls the SHARED renderer
(lib/render.py) with the leak gate on. This is the deterministic engine behind
the /forge:emit command; the command doc is the human-facing procedure.

ONE config, N TARGETS. The org tier is host-neutral: the same .forge.org.yaml can
be emitted as a Claude Code plugin (`--target claude-code`, the default) or as an
opencode configuration (`--target opencode`). The skill bodies are SHARED byte-for-byte
between targets; only the host packaging (manifest vs opencode.json, agents/ vs agent/,
hooks vs plugin/) and the few host-specific lines behind {{#TARGET_*}} conditionals
differ.

The opencode artifact is BACK/FORWARD COMPATIBLE: one emitted package runs unchanged
on opencode 1.18.29+ (the plugins' `server()` entrypoint) and on 2.x (`setup()`), so
an org re-emitting after a host upgrade — or distributing to machines on either —
ships ONE artifact. `emit --target opencode` also detects the installed opencode and
refuses hosts below the 1.18.29 floor (see check_opencode_host).

Usage:
  uv run --with pyyaml python lib/emit.py --config <.forge.org.yaml> --out <dir> \
      [--target claude-code|opencode]
"""
import argparse
import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import render_tree, render_file, extract_snippet  # noqa: E402

FORGE_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_TOKENS = {"acme", "Acme", "janedoe", "Jane Doe", "example", "example-project"}

# Canonical verb names the templates ship with. An org may rename any of them via the
# `verbs:` map in .forge.org.yaml (e.g. Acme: inception->plot, execute->engage,
# gate->clearance). Verb-picking is part of building an org's forge product — the
# generator stays neutral; the names are the org's creative choice. Each canonical
# skill lives at templates/org-plugin/skills/<canonical>/; emit renames the rendered
# dir to the org's word and substitutes {{VERB_<CANONICAL>}} everywhere it's referenced.
CANONICAL_VERBS = [
    "intro", "setup", "prime", "inception", "refine", "execute", "gate", "wiki", "handoff",
    # ADR 0019 §3: the verb that launches the read-only triage worker graph. Its skill
    # emits only when a worker graph binds it (a /triage with no worker to launch is dead).
    "triage",
]


def resolve_verbs(cfg):
    """canonical name -> org's chosen name (defaults to canonical when unset)."""
    overrides = cfg.get("verbs", {}) or {}
    unknown = set(overrides) - set(CANONICAL_VERBS)
    if unknown:
        raise SystemExit(f"verbs: unknown verb key(s) {sorted(unknown)}; "
                         f"valid: {CANONICAL_VERBS}")
    return {v: overrides.get(v, v) for v in CANONICAL_VERBS}


# model_policy is the ORG's model floor for ALL agent work (named roles AND any ad-hoc
# agent() in a hand-authored Workflow). It is OPTIONAL and configurable per org — the
# generator never hardcodes a floor, so when the block is absent we supply sane, NEUTRAL
# defaults rather than requiring it. Exposed as scalars the same way agent models are,
# so the rendered skills can surface each org's floor via {{MODEL_POLICY_*}}.
MODEL_POLICY_DEFAULTS = {
    "default": "the role's configured model",
    "banned": [],
    "rule": "Set model explicitly on ad-hoc Agent spawns; never leave it implicit.",
}


def model_policy_scalars(cfg):
    """Read optional cfg['model_policy'] → MODEL_POLICY_* scalars (all strings)."""
    mp = cfg.get("model_policy", {}) or {}
    banned = mp.get("banned", MODEL_POLICY_DEFAULTS["banned"])
    if isinstance(banned, (list, tuple)):
        banned = ", ".join(str(b) for b in banned)
    return {
        "MODEL_POLICY_DEFAULT": str(mp.get("default", MODEL_POLICY_DEFAULTS["default"])),
        "MODEL_POLICY_BANNED": str(banned),
        "MODEL_POLICY_RULE": str(mp.get("rule", MODEL_POLICY_DEFAULTS["rule"])),
    }


def require(cond, msg):
    if not cond:
        raise SystemExit(f"emit: {msg}")


# --- the graph catalog (ADR 0019) ---------------------------------------------------
# hyperdrive declares a CATALOG of named graphs (`graphs:`), each either its own WORKER
# agent (a bounded graph-agent in an isolated context, dispatched by a verb, ending with a
# result line) or walked by the interactive MAIN THREAD through its verb's skill. A graph
# is data: its node-set, transitions, loop caps and launch contract; its body is a
# per-graph template (templates/graphs/<graph>/agent.md.template for a worker). Every
# rule below is fail-closed: a mis-declared catalog refuses to emit.
LAUNCH_MODES = ("worker", "main_thread")
ISOLATION_MODES = ("worktree", "none")
TOOL_MODES = ("write", "read_only")
GRAPHS_DIR = FORGE_ROOT / "templates/graphs"
# Node skills live in their OWN namespace (ADR 0019 §1), never an orchestrator verb:
# templates/node-skills/<name>/SKILL.md.template, rendered only when a graph binds them.
NODE_SKILLS_DIR = FORGE_ROOT / "templates/node-skills"
# Rubrics are DISCOVERED by glob — no registry — so a rubric is added by adding its
# template, without touching this file.
RUBRICS_DIR = FORGE_ROOT / "templates/org-plugin/rubrics"
# Graph files that are NOT session skills (TEC-4098): every node skill a worker does not
# preload (its non-entry nodes) and every main_thread graph's index. Each lands as a plain
# file in this dir, beside the rubrics, and is read by the path its graph index names —
# a skill would cost every session an always-on listing line and be model-invocable from
# the main session (ADR 0019 §4, ADR 0003).
NODE_DIRS = {"claude-code": "nodes", "opencode": "node"}
# The ONE result-line format a worker ends every run with, on both targets; the
# execute verb consumes exactly this (and verifies it against gh + the tracker).
RESULT_LINE = ("RESULT: <PASS|FAIL|BLOCKED|CAPPED> | task=<key> | pr=<url|none> | "
               "branch=<branch>@<short-sha> | tests=<exact command> -> <passed>/<failed> | "
               "note=<one short line>")
# The tools a plugin subagent actually receives (dogfood 2026-09-23: a worker listing
# Read, Edit, Write, Bash, Grep, Glob, TodoWrite got only Read, Edit, Write, Bash). A
# worker never carries a fan-out tool (Agent, Skill) — it cannot spawn or load a verb.
CC_WRITE_TOOLS = ["Read", "Edit", "Write", "Bash"]
# Capabilities a read-only surface may NEVER carry: write/exec/delegate.
GRAPH_READONLY_SURFACE_FORBIDDEN = ["edit", "write", "patch", "bash", "task", "dispatch"]
# ...and their Claude Code tool names, which a read_only graph's `allow` may not name
# (on CC a named tool is granted verbatim; on opencode `edit` would lift the edit deny).
CC_WRITE_TOOL_NAMES = ["notebookedit", "multiedit"]


def _positive_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v > 0


def _targets(node) -> list:
    nxt = node.get("next")
    if nxt is None:
        return []
    return nxt if isinstance(nxt, list) else [nxt]


# The hard cut (ADR 0019 §1; forge 0.8.0 precedent): no shim — a leftover key fails with
# the exact migration, so an org's first 0.9.0 emit tells it what to move where.
LEGACY_KEYS = {
    "graph": ("`graph:` was replaced by the `graphs:` catalog in forge 0.9.0 (ADR 0019). "
              "Move the block under `graphs.build` and add `agent: builder`, "
              "`verb: execute`, `launch: worker`, `isolation: worktree`, `tools: write`; "
              "replace `max_fix_loops: N` with `max_visits: N+1` on the review node; drop "
              "node `effort`/`mode`; move `supplementary_reviewer` to the top level."),
    "agents": ("`agents:` was folded into the `graphs:` catalog in forge 0.9.0 (ADR 0019): "
               "set an optional pin as `graphs.<name>.model` / `graphs.<name>.effort` on "
               "the worker graph, then delete `agents:`."),
}


def _strongly_connected(nodes: dict) -> list[list[str]]:
    """Tarjan's SCCs over the `next` edges (graphs are small; recursion is fine)."""
    index, low, stack, on, out = {}, {}, [], set(), []

    def visit(v):
        index[v] = low[v] = len(index)
        stack.append(v)
        on.add(v)
        for w in _targets(nodes[v]):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(comp)

    for v in nodes:
        if v not in index:
            visit(v)
    return out


def check_graph_structure(where: str, nodes: dict, entry: str) -> None:
    """Fail closed unless every node is reachable from entry, a terminal exists, and
    every loop (non-trivial SCC of `next`) holds a max_visits node (ADR 0019 §5)."""
    seen, todo = {entry}, [entry]
    while todo:
        for t in _targets(nodes[todo.pop()]):
            if t not in seen:
                seen.add(t)
                todo.append(t)
    unreachable = sorted(set(nodes) - seen)
    require(not unreachable,
            f"{where}: node(s) {unreachable} are unreachable from entry {entry!r}")
    require(any("terminal" in n for n in nodes.values()),
            f"{where}: no terminal node — a graph that cannot end loops until its cap")
    # Every cycle must pass through a capped node <=> the subgraph of UNCAPPED nodes is
    # acyclic. (Stricter than "each SCC holds a cap": a self-loop beside a capped node in
    # the same SCC would otherwise spin forever without ever reaching the cap.)
    uncapped = {n: {**node, "next": [t for t in _targets(node) if "max_visits" not in nodes[t]]}
                for n, node in nodes.items() if "max_visits" not in node}
    for comp in _strongly_connected(uncapped):
        if len(comp) > 1 or comp[0] in _targets(uncapped[comp[0]]):
            require(False,
                    f"{where}: the loop {sorted(comp)} has no max_visits node — every loop "
                    f"needs a visit cap (an uncapped loop runs until the host stops it)")


GRAPH_KEYS = {"agent", "verb", "launch", "isolation", "tools", "allow", "deny", "mcp_servers",
              "max_total_steps", "result", "model", "effort", "entry", "nodes",
              "description"}
NODE_KEYS = {"skill", "rubric", "next", "terminal", "max_visits", "gate", "goal",
             "guidance"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Host built-in agent names a worker may never take (ADR 0019 §4). opencode 2.x
# (plugin/agent.ts) + `plan` (1.x); Claude Code's built-in subagents. `validate` is the
# emitted supplementary reviewer. Compared case-insensitively.
OC_BUILTIN_AGENTS = ("build", "general", "explore", "compaction", "title", "summary", "plan")
CC_BUILTIN_AGENTS = ("Explore", "Plan", "general-purpose", "claude", "statusline-setup",
                     "claude-code-guide")
RESERVED_AGENTS = ("validate",)
# Tools that let a worker fan out or load a verb — never on a worker (ADR 0019 §4).
FAN_OUT_TOOLS = ("agent", "skill", "task", "workflow", "dispatch", "subagent")
AGENT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


def _disables_model_invocation(template: Path) -> bool:
    fm = template.read_text().split("---", 2)
    head = fm[1] if len(fm) == 3 else ""
    return bool(re.search(r"^disable-model-invocation:\s*true\s*$", head, re.M | re.I))


def check_model_pin(ref, where: str, banned: list[str]) -> None:
    """A worker's model pin (target-neutral): a non-empty string off the banned list.
    The opencode layer additionally requires a full on-provider ref."""
    require(isinstance(ref, str) and ref, f"{where}: model must be a non-empty string")
    model_id = ref.split("/", 1)[-1].lower()
    hit = next((b for b in banned if b in model_id), None)
    require(not hit, f"{where}: model {ref!r} is banned by the org's model policy ({hit})")


def graph_catalog(cfg: dict, verbs: dict) -> list[dict]:
    """Validate the top-level `graphs:` catalog; return the normalized graphs.

    Target-neutral: both targets bind the SAME catalog. Each returned graph carries its
    name, launch contract and node-set, with its verb resolved to the canonical name.
    """
    for key, migration in LEGACY_KEYS.items():
        require(key not in cfg, migration)
    graphs = cfg.get("graphs")
    require(isinstance(graphs, dict) and graphs,
            "graphs: the top-level graph catalog is required — each named graph is a "
            "worker agent or a main-thread walk (ADR 0019)")
    by_org_name = {name: canon for canon, name in verbs.items()}
    verb_names = set(verbs) | set(verbs.values())
    node_skills = set(discover_node_skills())
    rubrics = set(discover_rubrics())
    clash = sorted(node_skills & verb_names)
    require(not clash, f"node skill(s) {clash} share a name with a verb — node skills live "
                       f"in their own namespace (ADR 0019 §1)")
    banned = [str(b).lower() for b in ((cfg.get("model_policy") or {}).get("banned") or [])]
    primary = (cfg.get("opencode") or {}).get("primary_agent", "build")
    builtins = {n.lower() for n in OC_BUILTIN_AGENTS + CC_BUILTIN_AGENTS}
    out, bound_verbs, agents = [], {}, {}
    for gname, g in graphs.items():
        where = f"graphs.{gname}"
        require(isinstance(g, dict), f"{where} must be a mapping")
        unknown = sorted(set(g) - GRAPH_KEYS)
        require(not unknown, f"{where}: unknown key(s) {unknown} (valid: {sorted(GRAPH_KEYS)})")
        launch = g.get("launch")
        require(launch in LAUNCH_MODES,
                f"{where}.launch must be one of {list(LAUNCH_MODES)} (got {launch!r})")
        tools = g.get("tools")
        require(tools in TOOL_MODES,
                f"{where}.tools must be one of {list(TOOL_MODES)} (got {tools!r})")
        verb = g.get("verb")
        canon = verb if verb in verbs else by_org_name.get(verb)
        require(canon is not None,
                f"{where}.verb {verb!r} is not a verb (canonical: {CANONICAL_VERBS}; "
                f"org names: {sorted(by_org_name)})")
        require(canon not in bound_verbs,
                f"{where}: verb {canon!r} is bound by both {bound_verbs.get(canon)!r} and "
                f"{gname!r} — a verb launches or is exactly one graph")
        bound_verbs[canon] = gname
        worker = launch == "worker"
        # The triage verb launches ONE read-only worker (ADR 0019 §3, §8): it drafts and
        # never writes, so a writer or a main-thread walk bound to it does not emit.
        require(canon != "triage" or (worker and tools == "read_only"),
                f"{where}: the `triage` verb launches a read_only worker graph "
                f"(launch: worker, tools: read_only) — got launch {launch!r}, tools {tools!r}")
        isolation = g.get("isolation", None if worker else "none")
        require(isolation in ISOLATION_MODES,
                f"{where}.isolation must be one of {list(ISOLATION_MODES)} "
                f"(got {isolation!r})")
        require(worker or isolation == "none",
                f"{where}: a main_thread graph runs in the engineer's session — its "
                f"isolation can only be `none` (got {isolation!r})")
        allow = g.get("allow", [])
        require(isinstance(allow, list) and all(isinstance(a, str) and a for a in allow),
                f"{where}.allow must be a list of exact tool / MCP-tool / shell-pattern names")
        wr = sorted(a for a in allow if a.lower() in
                    GRAPH_READONLY_SURFACE_FORBIDDEN + CC_WRITE_TOOL_NAMES)
        require(not (tools == "read_only" and wr),
                f"{where}: a read_only graph's allow grants write/exec tool(s) {wr} — "
                f"read_only means no Edit/Write and no unrestricted shell (ADR 0019 §1)")
        fan = sorted(a for a in allow if a.lower() in FAN_OUT_TOOLS)
        require(not (worker and fan),
                f"{where}.allow grants fan-out tool(s) {fan} — a worker cannot spawn, "
                f"dispatch or load a verb (ADR 0019 §4)")
        mcp = mcp_server_map(g.get("mcp_servers", {}), where)
        # `deny`: exact MCP tool names (mcp__<server>__<tool>) the worker may never call,
        # on either target (CC disallowedTools; opencode `<server>_<tool>: deny`, last).
        deny = g.get("deny", [])
        require(isinstance(deny, list) and all(isinstance(d, str) and _mcp_parts(d)
                                               for d in deny),
                f"{where}.deny takes only exact MCP tool names (mcp__<server>__<tool>) — "
                f"built-in write tools are already walled by `tools: read_only`")
        if canon == "triage":
            # ADR 0019 §8: no triage probe ever switches a shared MCP server's region — it
            # is a process-global toggle every other client of that server also sees.
            deny = deny + [f"mcp__{m}__{ENV_SWITCH_TOOL}" for m in mcp
                           if f"mcp__{m}__{ENV_SWITCH_TOOL}" not in deny]
        both = sorted(set(allow) & set(deny))
        require(not both, f"{where}: tool(s) {both} are in both allow and deny")
        # Every MCP tool is named by its mcp_servers HANDLE (mcp__<handle>__<tool>): the
        # handle is what resolves to each host's own server name (graph_for_target).
        undeclared = sorted({_mcp_parts(a)[0] for a in allow + deny if _mcp_parts(a)}
                            - set(mcp))
        require(not undeclared,
                f"{where}: allow/deny name MCP tools of undeclared server(s) {undeclared} — "
                f"list each in mcp_servers (handle -> per-host names) and name its tools "
                f"mcp__<handle>__<tool>; a read_only worker denies every other MCP tool")
        agent = g.get("agent")
        if worker:
            require(isinstance(agent, str) and AGENT_NAME_RE.match(agent or "") is not None
                    or agent in CC_BUILTIN_AGENTS,
                    f"{where}.agent is required for a worker graph — the emitted agent's "
                    f"name (lowercase, [a-z0-9-])")
            require(agent.lower() not in builtins and agent.lower() not in RESERVED_AGENTS,
                    f"{where}.agent {agent!r} collides with a host built-in or reserved "
                    f"agent name ({sorted(OC_BUILTIN_AGENTS + CC_BUILTIN_AGENTS + RESERVED_AGENTS)}) "
                    f"— the worker must be its own identity (ADR 0019 §4)")
            require(agent != primary,
                    f"{where}.agent {agent!r} is the opencode primary_agent — the "
                    f"orchestrator and a worker never share a definition (ADR 0019 §4)")
            require(agent not in agents,
                    f"{where}: agent {agent!r} is declared by more than one graph "
                    f"({agents.get(agent)!r} too)")
            agents[agent] = gname
            # HARD total cap — presence REQUIRED (silence is fail-open). It emits as the
            # host cap on the worker agent (CC maxTurns, opencode steps).
            require(_positive_int(g.get("max_total_steps")),
                    f"{where}.max_total_steps must be a positive int — a worker graph with "
                    f"no declared cap does not emit (silence is fail-open)")
        elif "max_total_steps" in g:
            require(_positive_int(g["max_total_steps"]),
                    f"{where}.max_total_steps must be a positive int")
        if "model" in g:
            check_model_pin(g["model"], f"{where}.model", banned)
        if "effort" in g:
            require(g["effort"] in EFFORTS,
                    f"{where}.effort must be one of {list(EFFORTS)} (got {g['effort']!r})")
        nodes = copy.deepcopy(g.get("nodes"))  # normalized below; never mutate the config
        require(isinstance(nodes, dict) and nodes,
                f"{where}.nodes is required — the explicit states the graph walks")
        entry = g.get("entry")
        require(isinstance(entry, str) and entry in nodes,
                f"{where}.entry must name a declared node (got {entry!r}; "
                f"nodes: {sorted(nodes)})")
        for name, node in nodes.items():
            nw = f"{where}.nodes.{name}"
            require(isinstance(node, dict), f"{nw} must be a mapping (the node's contract)")
            bad = sorted(set(node) - NODE_KEYS)
            require(not bad,
                    f"{nw}: unknown key(s) {bad} (valid: {sorted(NODE_KEYS)}; a node changes "
                    f"skill, rubric and tool guidance, never effort — ADR 0019 §6)")
            require(("skill" in node) ^ ("rubric" in node),
                    f"{nw} must carry exactly one of skill|rubric")
            require(("terminal" in node) ^ ("next" in node),
                    f"{nw} must carry exactly one of next|terminal")
            for t in _targets(node):
                require(t in nodes, f"{nw}.next → {t!r} is not a declared node")
            for k in ("goal", "guidance"):
                if k in node:
                    require(isinstance(node[k], str), f"{nw}.{k} must be a string")
                    bad_refs = sorted({s for s, _ in _MCP_REF_RE.findall(node[k])} - set(mcp))
                    require(not bad_refs,
                            f"{nw}.{k} names MCP tools of undeclared server(s) {bad_refs} — "
                            f"name them mcp__<handle>__<tool> with a handle from "
                            f"mcp_servers, so each host renders its own tool name")
            if "max_visits" in node:
                require(_positive_int(node["max_visits"]),
                        f"{nw}.max_visits must be a positive int (the loop cap)")
            if "gate" in node:
                require(not worker,
                        f"{nw}: `gate:` is main_thread-only — a worker never asks the human; "
                        f"it ends `parked:<node>` with its state in the tracker (ADR 0019 §2)")
                require(isinstance(node["gate"], str) and node["gate"],
                        f"{nw}.gate must name its signer")
            if "skill" in node:
                sk = node["skill"]
                if sk in verb_names:
                    require(not worker,
                            f"{nw}: skill {sk!r} is a verb — a verb as a worker node skill "
                            f"hands the worker orchestrator prose; bind a node skill "
                            f"(templates/node-skills/) instead (ADR 0019 §4)")
                    node["skill"] = by_org_name.get(sk, sk)  # canonical; renders as org name
                else:
                    require(sk in node_skills,
                            f"{nw}: skill {sk!r} is not a node skill "
                            f"(templates/node-skills/: {sorted(node_skills)}) nor a verb")
            else:
                require(node["rubric"] in rubrics,
                        f"{nw}: rubric {node['rubric']!r} is not a rubric "
                        f"(templates/org-plugin/rubrics/: {sorted(rubrics)})")
        check_graph_structure(where, nodes, entry)
        if worker:
            e = nodes[entry]
            if "skill" in e and e["skill"] in node_skills:
                require(not _disables_model_invocation(
                    NODE_SKILLS_DIR / e["skill"] / "SKILL.md.template"),
                    f"{where}: the entry node's skill {e['skill']!r} sets "
                    f"disable-model-invocation — a worker preloads it, and a skill that "
                    f"disables model invocation cannot be preloaded (ADR 0019 §4)")
        out.append({
            "name": gname, "launch": launch, "tools": tools, "isolation": isolation,
            "verb": canon, "verb_name": verbs[canon], "agent": agent,
            "allow": list(allow), "deny": list(deny), "mcp_servers": mcp,
            "max_total_steps": g.get("max_total_steps"), "result": g.get("result"),
            "model": g.get("model"), "effort": g.get("effort"),
            "entry": entry, "nodes": nodes,
        })
    return out


# --- MCP server names are per HOST (TEC-4099) -------------------------------------------
# The same server has a different name on each host, so a graph names it by a HANDLE and
# declares one name per target:
#   claude-code — a plugin-provided server is `plugin_<plugin.json name>_<.mcp.json key>`
#                 (observed live: mcp__plugin_proscia-o11y_proscia-o11y__*); a user/project
#                 server (~/.claude.json, .mcp.json) is its own key. Tool: mcp__<name>__<tool>.
#   opencode    — the server's key in the user's config `mcp` block (2.x `mcp.servers.<key>`,
#                 1.x `mcp.<key>`: core/src/config/normalize.ts:260-283 @ v2.0.12); forge and
#                 the hyperdrive launcher ship no `mcp` block. Tool: oc_tool_key(name, tool)
#                 (core/src/tool/mcp.ts:16-17).
# There is no single-string form: forge cannot know a name is the same on both hosts, and
# assuming it is exactly the defect (every declared read denied on opencode). A name the
# target lacks refuses that target's emit (graph_for_target).
MCP_TARGETS = ("claude-code", "opencode")
_MCP_HANDLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
# An MCP tool reference in node prose: mcp__<handle>__<tool>.
_MCP_REF_RE = re.compile(r"mcp__([A-Za-z0-9._-]+?)__([A-Za-z0-9_-]+)")


def mcp_server_map(v, where: str) -> dict:
    """Validate `mcp_servers`: {handle: {claude-code: <name>, opencode: <name>}}."""
    require(isinstance(v, dict),
            f"{where}.mcp_servers must be a mapping of handle -> {{claude-code: <name>, "
            f"opencode: <name>}} — the hosts name one server differently (Claude Code: "
            f"`plugin_<plugin>_<server>` for a plugin server; opencode: its key in the "
            f"user's opencode `mcp` block). Migrate `[x]` to `x: {{claude-code: <CC name>, "
            f"opencode: <opencode key>}}` and name its tools mcp__x__<tool>")
    out = {}
    for h, names in v.items():
        hw = f"{where}.mcp_servers.{h}"
        require(isinstance(h, str) and _MCP_HANDLE_RE.match(h) and "__" not in h,
                f"{hw}: a handle is [A-Za-z0-9_-] with no `__` (it is parsed out of "
                f"mcp__<handle>__<tool>)")
        require(isinstance(names, dict),
                f"{hw} is a single name {names!r} — ambiguous: the hosts name a server "
                f"differently, so give each explicitly ({{claude-code: <name>, opencode: "
                f"<name>}}), writing it twice when it truly is the same on both")
        unknown = sorted(set(names) - set(MCP_TARGETS))
        require(not unknown, f"{hw}: unknown target key(s) {unknown} "
                             f"(valid: {list(MCP_TARGETS)})")
        require(names, f"{hw} names no target — give claude-code: and/or opencode:")
        for t, n in names.items():
            require(isinstance(n, str) and n and not re.search(r"\s", n) and "__" not in n,
                    f"{hw}.{t} must be a non-empty server name with no whitespace and no "
                    f"`__` (Claude Code splits mcp__<server>__<tool> on it)")
        out[h] = dict(names)
    return out


def graph_for_target(g: dict, target: str) -> dict:
    """A validated graph as ONE target emits it: every MCP handle resolves to the target's
    own server name — `mcp_servers` becomes that host's name list, allow/deny become
    mcp__<host name>__<tool> (the opencode layer turns them into oc_tool_key), and a
    node's goal/guidance names each tool as the host spells it. A server with no name for
    this target refuses (its permission keys cannot be written for this host)."""
    names = {}
    for h, per in g["mcp_servers"].items():
        require(target in per,
                f"graphs.{g['name']}.mcp_servers.{h} has no `{target}` name — this target "
                f"cannot write that server's MCP permission keys, so a read_only worker "
                f"would deny every declared read; add `{target}: <name>` (claude-code: the "
                f"session's server name, e.g. plugin_<plugin>_<server>; opencode: the key "
                f"in the user's opencode config `mcp` block)")
        names[h] = per[target]

    def tool(ref):
        server, t = _mcp_parts(ref)
        return f"mcp__{names[server]}__{t}"

    def prose(text):
        return _MCP_REF_RE.sub(
            lambda m: (f"mcp__{names[m[1]]}__{m[2]}" if target == "claude-code"
                       else oc_tool_key(names[m[1]], m[2])), text)

    nodes = {n: {**node, **{k: prose(node[k]) for k in ("goal", "guidance") if k in node}}
             for n, node in g["nodes"].items()}
    return {**g, "target": target, "mcp_by_target": g["mcp_servers"],
            "mcp_tools": _mcp_tools_named(g),
            "mcp_servers": [names[h] for h in g["mcp_servers"]],
            "allow": [tool(a) if _mcp_parts(a) else a for a in g["allow"]],
            "deny": [tool(d) for d in g["deny"]], "nodes": nodes}


def _mcp_tools_named(g: dict) -> dict:
    """handle -> the tools a (target-neutral) graph names: allow, deny, node prose."""
    out = {h: set() for h in g["mcp_servers"]}
    for ref in g["allow"] + g["deny"]:
        if _mcp_parts(ref):
            out[_mcp_parts(ref)[0]].add(_mcp_parts(ref)[1])
    for node in g["nodes"].values():
        for k in ("goal", "guidance"):
            for h, t in _MCP_REF_RE.findall(node.get(k, "")):
                out[h].add(t)
    return out


def discover_rubrics() -> list[str]:
    return sorted(p.name[: -len(".md.template")] for p in RUBRICS_DIR.glob("*.md.template"))


def discover_node_skills() -> list[str]:
    if not NODE_SKILLS_DIR.is_dir():
        return []
    return sorted(d.name for d in NODE_SKILLS_DIR.iterdir()
                  if (d / "SKILL.md.template").is_file())


def index_skill(g: dict) -> str:
    """The graph's T1 index skill — its node walk, caps and result line."""
    return f"{g['name']}-graph"


def node_skill_name(node: dict, verbs: dict) -> str:
    """A node's skill as emitted: a verb (main_thread only) maps to the org's name."""
    s = node["skill"]
    return verbs.get(s, s)


def node_is_skill(g: dict, name: str, verbs: dict) -> bool:
    """A skill node emits as a session skill only when it binds a verb (already a skill)
    or is a worker's preloaded entry; every other node is a path-read file (TEC-4098)."""
    return g["nodes"][name]["skill"] in verbs or (
        g["launch"] == "worker" and name == g["entry"])


def worker_preloads(g: dict, verbs: dict) -> list[str]:
    """What a worker preloads (ADR 0019 §4): its graph index + its entry node's skill.
    Every other node skill and rubric is read by path on entry (ADR 0003)."""
    pre = [index_skill(g)]
    entry = g["nodes"][g["entry"]]
    if "skill" in entry:
        pre.append(node_skill_name(entry, verbs))
    return pre


def execute_worker(graphs: list[dict]) -> dict:
    """The worker graph the execute verb dispatches — one builder per ready task."""
    hits = [g for g in graphs if g["verb"] == "execute" and g["launch"] == "worker"]
    require(hits, "graphs: no worker graph binds the `execute` verb — it is the graph "
                  "that verb dispatches (one builder per ready task)")
    return hits[0]


def verb_worker(graphs: list[dict], canon: str) -> dict | None:
    """The worker graph a launching verb dispatches, if the catalog declares one."""
    return next((g for g in graphs if g["verb"] == canon and g["launch"] == "worker"), None)


def triage_scalars(graphs: list[dict]) -> dict:
    """What the /triage verb skill needs of its worker (empty when none is declared —
    the verb then does not emit at all)."""
    t = verb_worker(graphs, "triage")
    return {
        "TRIAGE_AGENT": t["agent"] if t else "",
        "TRIAGE_MCP_SERVERS": ", ".join(f"`{m}`" for m in t["mcp_servers"]) if t else "",
        "TRIAGE_MAX_STEPS": str(t["max_total_steps"]) if t else "",
        "TRIAGE_LOOP_CAPS": "; ".join(f"`{n}` at most {node['max_visits']} visits"
                                      for n, node in t["nodes"].items()
                                      if "max_visits" in node) if t else "",
        "TRIAGE_RESULT_LINE": (t.get("result") or RESULT_LINE) if t else "",
    }


def supplementary_reviewer(cfg: dict) -> dict:
    """The OPTIONAL supplementary reviewer (ADR 0018 §5 as amended by ADR 0019 §7): a
    read-only agent on both targets, run on a COMPLETED PR, never inside the loop."""
    supp = cfg.get("supplementary_reviewer")
    require(isinstance(supp, dict) and "enabled" in supp,
            "supplementary_reviewer is required (at least `enabled`) — the optional "
            "fresh-context reviewer for a completed PR (ADR 0018 §5)")
    if supp.get("enabled"):
        require(supp.get("fresh_context") is True,
                "supplementary_reviewer.fresh_context must be true when enabled — "
                "independence from the build context is its whole point")
        surface = supp.get("read_surface")
        require(isinstance(surface, list) and surface,
                "supplementary_reviewer.read_surface must be a non-empty list")
        bad = sorted(set(str(a).lower() for a in surface) & set(GRAPH_READONLY_SURFACE_FORBIDDEN))
        require(not bad,
                f"supplementary_reviewer.read_surface carries write/delegate "
                f"capabilities {bad} — the supplementary reviewer is read-only by contract "
                f"(forbidden: {GRAPH_READONLY_SURFACE_FORBIDDEN})")
        # max_steps stays REQUIRED — it is a CAP (fail-closed), not a depth pin.
        require(_positive_int(supp.get("max_steps")),
                "supplementary_reviewer.max_steps must be a positive int")
        if "model" in supp:
            require(isinstance(supp.get("model"), str) and supp["model"],
                    "supplementary_reviewer.model, when set, must be a non-empty string "
                    "(a full provider/model ref; validated on-provider by the opencode target)")
    return supp


def walk_order(nodes: dict, entry: str) -> list[str]:
    """Nodes in breadth-first walk order from entry (the reading order of the index),
    independent of the config's key order; every node is reachable (checked)."""
    order, todo = [entry], [entry]
    while todo:
        for t in _targets(nodes[todo.pop(0)]):
            if t not in order:
                order.append(t)
                todo.append(t)
    return order + [n for n in nodes if n not in order]


def _node_rel(kind: str, name: str, target: str) -> str:
    """Where a node's file lands in the emitted tree, relative to its root."""
    if kind == "node":
        return f"{NODE_DIRS[target]}/{name}.md"
    if target == "claude-code":
        return f"skills/{name}/SKILL.md" if kind == "skill" else f"rubrics/{name}.md"
    return f"skill/{name}/SKILL.md" if kind == "skill" else f"rubric/{name}.md"


def _node_ref(rel: str, target: str) -> str:
    """How the graph index spells a path: plugin-root-anchored on Claude Code, relative
    to the opencode config directory on opencode."""
    return "${CLAUDE_PLUGIN_ROOT}/" + rel if target == "claude-code" else rel


def node_lines(g: dict, target: str, verbs: dict | None = None) -> list[dict]:
    """The rendered node walk for one graph on one target (paths are host-specific).
    Each item carries its `line` and the `path` (relative to the emitted root) it names."""
    verbs = verbs or {}
    lines = []
    for name in walk_order(g["nodes"], g["entry"]):
        node = g["nodes"][name]
        if "skill" in node:
            s = node_skill_name(node, verbs)
            kind = "skill" if node_is_skill(g, name, verbs) else "node"
            rel = _node_rel(kind, s, target)
            carries = f"{kind} `{s}` (`{_node_ref(rel, target)}`)"
        else:
            r = node["rubric"]
            rel = _node_rel("rubric", r, target)
            carries = f"rubric `{r}` (`{_node_ref(rel, target)}`)"
        if "terminal" in node:
            flow = f"terminal `{node['terminal']}`"
        else:
            flow = "→ " + " | ".join(f"`{t}`" for t in _targets(node))
        extra = ""
        if "max_visits" in node:
            extra += f"; at most {node['max_visits']} visits"
        if "gate" in node:
            extra += f"; gate: {node['gate']} (human sign-off)"
        if node.get("goal"):
            extra += f". Goal: {node['goal']}"
        if node.get("guidance"):
            extra += f". Tools: {node['guidance']}"
        lines.append({"line": f"- **{name}** — {carries} {flow}{extra}", "path": rel})
    return lines


OC_WORKER_ALWAYS_DENY = ("dispatch", "subagent", "task", "question")
_TOOL_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _is_shell_pattern(a: str) -> bool:
    return not a.startswith("mcp__") and not _TOOL_NAME_RE.match(a)


# The tool both shared MCP servers register to switch their process-global region (ADR
# 0019 §8); a triage worker denies it on every server it declares.
ENV_SWITCH_TOOL = "set_environment"


def _mcp_parts(name: str) -> tuple[str, str] | None:
    """`mcp__<server>__<tool>` -> (server, tool); anything else -> None."""
    if not name.startswith("mcp__"):
        return None
    parts = name[len("mcp__"):].split("__", 1)
    return (parts[0], parts[1]) if len(parts) == 2 and all(parts) else None


def _oc_sanitize(v: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", v)


def oc_tool_key(server: str, tool: str) -> str:
    """opencode's MCP tool name (mcp/catalog.ts toolName): sanitized server + `_` + tool."""
    return f"{_oc_sanitize(server)}_{_oc_sanitize(tool)}"


# A read_only worker's opencode catch-all (TEC-4097), FIRST so the allowlist after it can
# lift it: `*_*` resource `?` denies every MCP tool of ANY server — declared or not, and one
# a session adds after emit. An MCP call asks action `<server>_<tool>` (always an `_`) with
# resource "*" (one char, which `?` matches); the host's other `_` actions
# (external_directory, doom_loop) ask a path / a tool name, so the catch-all never reaches
# them. `opencode_*` removes 2.x's `opencode_session_*` tools, which assert no permission:
# only a resource-"*" deny drops them from the toolset. Verified against opencode 1.18.20
# (permission/index.ts:28-38 evaluate, session/tools.ts:408) and upstream v2.0.12
# (core/src/permission.ts:87-97 evaluate, core/src/tool/mcp.ts:16-17,51-53,
# core/src/tool.ts:229-231,292-295); both decide by the LAST rule matching action AND resource.
OC_READ_ONLY_CATCH_ALL = [("*_*", {"?": "deny"}), ("opencode_*", "deny")]


def oc_mcp_rules(g: dict) -> list[tuple[str, str | dict]]:
    """The worker's ORDERED MCP permission rules (opencode decides by the LAST matching
    rule): a read_only worker denies every MCP tool of every server (the catch-all), then
    each declared server's tools by default (`<server>_*`, which also hides them), then
    allows its exact read allowlist; every `deny` name comes last, so it holds whatever
    precedes it."""
    rules = []
    if g["tools"] == "read_only":
        rules += OC_READ_ONLY_CATCH_ALL
        rules += [(f"{_oc_sanitize(m)}_*", "deny") for m in g.get("mcp_servers", [])]
        rules += [(oc_tool_key(*_mcp_parts(a)), "allow") for a in g.get("allow", [])
                  if _mcp_parts(a)]
    rules += [(oc_tool_key(*_mcp_parts(d)), "deny") for d in g.get("deny", [])]
    return rules


def oc_worker_permission(g: dict) -> dict:
    """An opencode worker's permission block (ADR 0019 §4): a worker never dispatches,
    spawns a native subagent (`subagent` on 2.x, `task` on 1.x) or asks the human. A
    read_only worker also denies edit + egress and its shell is an allowlist of the
    graph's shell patterns (`"*": deny` when it declares none)."""
    deny = set(OC_WORKER_ALWAYS_DENY)
    bash = None
    if g["tools"] == "read_only":
        allowed = {a.lower() for a in g.get("allow", []) if not _is_shell_pattern(a)}
        deny |= {c for c in ("edit", "webfetch", "websearch") if c not in allowed}
        bash = [a for a in g.get("allow", []) if _is_shell_pattern(a)]
    return {"deny": deny, "bash": bash, "mcp": oc_mcp_rules(g)}


def _oc_rule_yaml(rule) -> str:
    """A permission rule's YAML value: an effect, or a {resource pattern: effect} map."""
    if isinstance(rule, str):
        return rule
    return "{" + ", ".join(f'"{r}": {e}' for r, e in rule.items()) + "}"


def cc_worker_tools(g: dict) -> tuple[list[str], list[str]]:
    """A Claude Code worker's (tools, disallowedTools). write = the host's write set; a
    read_only worker gets Read (+ Bash only when it declares shell patterns — the shell
    wall is then instruction-level on CC) and disallows Edit/Write. Exact tool and MCP
    tool names from `allow` are added."""
    allow = g.get("allow", [])
    named = [a for a in allow if not _is_shell_pattern(a)]
    if g["tools"] == "write":
        base, disallowed = list(CC_WRITE_TOOLS), []
    else:
        base = ["Read"] + (["Bash"] if any(_is_shell_pattern(a) for a in allow) else [])
        disallowed = ["Edit", "Write", "NotebookEdit"]
    tools = base + [t for t in named if t not in base]
    # the ADR 0019 Validation (a) fallback: name each denied MCP tool, beside the allowlist
    return tools, disallowed + [d for d in g.get("deny", []) if d not in disallowed]


def graph_bindings(base: dict, g: dict, target: str) -> dict:
    """Per-graph bindings layered over the org bindings (the render loop, ADR 0019)."""
    verbs = base["verbs"]
    visits = [f"`{n}` at most {node['max_visits']} visits"
              for n, node in g["nodes"].items() if "max_visits" in node]
    worker = g["launch"] == "worker"
    walker = (f"Walked by the `{g['agent']}` worker agent, in one context." if worker else
              f"Walked by the session running `{g['verb_name']}`, with the engineer.")
    result = g.get("result") or (RESULT_LINE if worker else
                                 f"the `{g['verb_name']}` skill's own report")
    result_md = (f"`{result}`" if (worker or g.get("result")) else result)
    cc_tools, cc_disallowed = cc_worker_tools(g)
    perm = oc_worker_permission(g)
    scalars = {
        **base["scalars"],
        "GRAPH_NAME": g["name"],
        "GRAPH_AGENT": g["agent"] or "",
        "GRAPH_ENTRY": g["entry"],
        "GRAPH_INDEX_SKILL": index_skill(g),
        "GRAPH_WALKER": walker,
        "GRAPH_RESULT_LINE": result,
        "GRAPH_RESULT_LINE_MD": result_md,
        "GRAPH_MAX_TOTAL_STEPS": str(g["max_total_steps"] or ""),
        "GRAPH_LOOP_CAPS": "; ".join(visits) or "none declared",
        "GRAPH_MODEL": g.get("model") or "inherit",
        "GRAPH_EFFORT": g.get("effort") or "",
        "GRAPH_CC_TOOLS": ", ".join(cc_tools),
        "GRAPH_CC_DISALLOWED": ", ".join(cc_disallowed),
    }
    arrays = {**base["arrays"],
              "GRAPH_NODES": node_lines(g, target, verbs),
              "GRAPH_PRELOADS": [{"skill": s} for s in worker_preloads(g, verbs)],
              "GRAPH_OC_DENY": [{"cap": c} for c in sorted(perm["deny"])],
              "GRAPH_OC_BASH": [{"pattern": p} for p in (perm["bash"] or [])],
              "GRAPH_OC_MCP": [{"key": k, "action": _oc_rule_yaml(a)}
                               for k, a in perm["mcp"]]}
    conditionals = {**base["conditionals"],
                    "GRAPH_EFFORT_SET": bool(g.get("effort")),
                    "GRAPH_HAS_GATES": any("gate" in n for n in g["nodes"].values()),
                    "GRAPH_CC_DISALLOWED_SET": bool(cc_disallowed),
                    "GRAPH_OC_BASH_RESTRICTED": perm["bash"] is not None}
    return {**base, "scalars": scalars, "arrays": arrays, "conditionals": conditionals}


def build_bindings(cfg: dict, target: str = "claude-code") -> dict:
    """Org bindings for one emit TARGET: the catalog is validated target-neutral, then
    each graph is resolved to that target's host-native names (graph_for_target)."""
    org, plugin, wiki, tracker = (
        cfg["org"], cfg["plugin"], cfg["org_wiki"], cfg["tracker"])

    # Identity must be filled in, not example-valued (emit.md step 1).
    for path, val in [
        ("org.name", org.get("name")), ("org.slug", org.get("slug")),
        ("plugin.name", plugin.get("name")),
        ("plugin.author.name", plugin.get("author", {}).get("name")),
        ("plugin.homepage", plugin.get("homepage")),
    ]:
        require(val, f"{path} is required")
        require(str(val) not in EXAMPLE_TOKENS,
                f"{path} still has an example value ({val!r}) — fill in your org")

    # Default-deny: no always-on cross-project promotion without an adjudicator.
    om = cfg.get("operating_model", {})
    require(not (om.get("capture_default") == "always-on"
                 and not om.get("cross_project_truth_adjudicator")),
            "operating_model: capture_default 'always-on' needs a "
            "cross_project_truth_adjudicator (default-deny)")

    tc = tracker["config"]
    snippet_vars = {
        "tracker.config.cloud_id": tc.get("cloud_id", ""),
        "tracker.config.project_key": tc.get("project_key", ""),
        "tracker.config.base_url": tc.get("base_url", ""),
        "tracker.config.repo": tc.get("repo", ""),
    }
    adapter = f"adapters/tracker/{tracker['type']}.md"

    verbs = resolve_verbs(cfg)
    verb_scalars = {f"VERB_{canon.upper()}": name for canon, name in verbs.items()}

    mp_scalars = model_policy_scalars(cfg)

    graphs = [graph_for_target(g, target) for g in graph_catalog(cfg, verbs)]
    builder = execute_worker(graphs)
    supp = supplementary_reviewer(cfg)
    supp_enabled = bool(supp.get("enabled"))

    return {
        "scalars": {
            **verb_scalars,
            **mp_scalars,
            "ORG_NAME": org["name"],
            "PLUGIN_NAME": plugin["name"],
            "PLUGIN_VERSION": plugin["version"],
            "PLUGIN_DESCRIPTION": plugin["description"],
            "PLUGIN_AUTHOR_NAME": plugin["author"]["name"],
            "PLUGIN_AUTHOR_URL": plugin["author"]["url"],
            "PLUGIN_HOMEPAGE": plugin["homepage"],
            "PLUGIN_LICENSE": plugin["license"],
            "ORG_WIKI_NAME": wiki["name"],
            "ORG_WIKI_REMOTE": wiki["remote"],
            "ORG_WIKI_PATH_ENV": wiki["local_path_env"],
            "ORG_WIKI_DEFAULT_PATH": wiki["default_local_path"],
            # Host nouns — the ONLY places a shared template names its host. The
            # opencode bindings override these; everything else stays identical.
            "HOST_NOUN": "a Claude Code plugin",
            # The dispatch noun: on both targets a ready task is one builder
            # graph-agent run (ADR 0018/0019), not a fan-out of role stages.
            "HOST_DISPATCH_NOUN": "graph-agent runs",
            # The worker the execute verb dispatches (ADR 0019: `builder`).
            "BUILD_AGENT": builder["agent"],
            "RESULT_LINE": RESULT_LINE,
            # the supplementary reviewer's host cap (a rendered-then-dropped file when off)
            "SUPP_MAX_STEPS": str(supp.get("max_steps") or 40),
            # The triage worker the triage verb launches (ADR 0019 §8), when declared.
            **triage_scalars(graphs),
        },
        "arrays": {"PRIME_READS": wiki["prime_reads"],
                   "READONLY_COMMANDS": [{"pattern": c} for c in
                                         readonly_commands(tracker["type"], strict=False)]},
        # Exactly one TARGET_* is true per emit. Shared templates gate host-specific
        # prose on these; a template with no conditional renders in every target.
        # SUPP_REVIEWER_ENABLED gates the optional-supplementary-reviewer prose/config.
        "conditionals": {"TARGET_CC": True, "TARGET_OPENCODE": False,
                         "SUPP_REVIEWER_ENABLED": supp_enabled,
                         "TRIAGE_ENABLED": verb_worker(graphs, "triage") is not None},
        # The validated catalog (not rendered directly; the per-graph render loop binds it).
        "graphs": graphs,
        "verbs": verbs,
        "snippets": [
            {"placeholder": p, "adapter": adapter, "label": p, "vars": snippet_vars}
            for p in ("TRACKER_PRIME_SNIPPET", "TRACKER_VIEW_ISSUE_SNIPPET",
                      "TRACKER_COMMENT_LIST_SNIPPET", "TRACKER_COMMENT_SNIPPET",
                      "TRACKER_CREATE_TASK_SNIPPET", "TRACKER_BACKLOG_SNIPPET",
                      "TRACKER_GATE_SNIPPET", "TRACKER_DOCTOR_SNIPPET")
        ],
    }


# --- opencode target -------------------------------------------------------------
# The dangerous capability set: write, command execution, delegation, egress. The
# OPTIONAL supplementary reviewer on opencode is made read-only by DENYING these (a
# bare-string `deny` removes the tool from the model's toolset AND refuses at exec).
# read/grep/glob/list stay default-allow — that is what a reviewer needs.
#
# The emitted deny block is DERIVED from the supplementary reviewer's own
# `read_surface` in the graph block: deny = DANGEROUS_CAPS - read_surface. The config
# is therefore load-bearing, not documentation — a write capability in the read
# surface fails the emit (graph_bindings, above).
DANGEROUS_CAPS = ["edit", "bash", "task", "dispatch", "webfetch", "websearch"]
# `bash` for a read-only reviewer is not a blanket deny but an ALLOWLIST: the tracker
# adapter's read commands (TRACKER_READONLY_COMMANDS) plus these SCM reads. A reviewer
# that cannot read its ticket or the diff wanders instead of judging.
SCM_READONLY_COMMANDS = ["git diff *", "git log *", "git show *", "git status*",
                         "gh pr diff *", "gh pr view *"]
# These may NEVER appear in a read-only surface: write/exec/delegate. `task`/`dispatch`
# are load-bearing — without them a "read-only" reviewer can spawn an unrestricted
# writer and launder writes. (graph_bindings enforces the same set on the graph block.)
OC_FORBIDDEN_IN_READONLY_ALLOW = GRAPH_READONLY_SURFACE_FORBIDDEN


def readonly_commands(tracker_type: str, strict: bool) -> list[str]:
    """The read-only shell set: the tracker adapter's TRACKER_READONLY_COMMANDS + the
    SCM reads. `strict` (opencode, where it becomes a hard permission allowlist) refuses
    an adapter without the section; Claude Code renders it as the reviewer's instruction."""
    path = FORGE_ROOT / f"adapters/tracker/{tracker_type}.md"
    try:
        block = extract_snippet(path.read_text(), "TRACKER_READONLY_COMMANDS", {})
    except (SystemExit, OSError):
        if strict:
            raise SystemExit(
                f"emit: tracker adapter '{tracker_type}' has no TRACKER_READONLY_COMMANDS "
                f"section — the opencode target needs it to grant the reviewer its tracker "
                f"reads (adapters with the full set: jira-acli, github)")
        block = ""
    cmds = [ln.strip() for ln in block.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    return cmds + SCM_READONLY_COMMANDS


def derived_deny(allow) -> list[str]:
    """The deny set a read surface implies: every dangerous cap NOT allowed."""
    allowed = {str(a).lower() for a in (allow or [])}
    return [c for c in DANGEROUS_CAPS if c not in allowed]


def oc_workers_table(graphs: list[dict]) -> dict:
    return {g["agent"]: {"isolation": g["isolation"]} for g in graphs
            if g["launch"] == "worker"}


def build_bindings_opencode(cfg: dict) -> dict:
    """Org bindings + the opencode-target layer. Fail-closed on every control."""
    b = build_bindings(cfg, "opencode")  # org scalars stay IDENTICAL across targets

    oc = cfg.get("opencode")
    require(isinstance(oc, dict) and oc,
            "opencode: block is required for --target opencode")

    # The provider is the org's choice and is ONLY an id: auth and provider options are
    # opencode's business (`opencode auth login`, `provider.<id>.options` if needed).
    prov = oc.get("provider") or {}
    require(prov.get("id"), "opencode.provider.id is required")
    require(set(prov) == {"id"},
            f"opencode.provider takes only `id`; got {sorted(set(prov) - {'id'})} — "
            f"provider options and credentials belong in opencode, not the org config")

    model = oc.get("model") or {}
    require(model.get("model"), "opencode.model.model is required")
    model_provider = model.get("provider") or prov["id"]

    # THE GRAPH (ADR 0018) is validated target-neutrally in graph_bindings (called by
    # build_bindings, above): the states one `build` graph-agent traverses, its loop
    # caps, and the review self-check node. The opencode layer here adds only what a
    # provider makes possible — the definition-time model policy (on-provider +
    # off-banned) — and the OPTIONAL supplementary reviewer's realization (agent file,
    # read-only permission block, task allowlist, subagent depth).
    #
    # The model policy is validated at EMIT time, not discovered at run time: the org
    # floor or the supplementary reviewer's pin, off-provider or banned, does not emit
    # (the glm-5.3 balance incident + the astra retention failure are the evidence — a
    # run with no explicit model inherits the host default, which can be banned/rejected).
    mp_cfg = cfg.get("model_policy", {}) or {}
    banned_models = [str(b).lower() for b in (mp_cfg.get("banned", []) or [])]

    def check_model_ref(ref, where):
        """A model ref must be on the org's provider and off the banned list."""
        require(isinstance(ref, str) and ref,
                f"{where}: model must be a non-empty string (got {ref!r})")
        prov_id = prov["id"]
        if "/" in ref:
            ref_prov, ref_model = ref.split("/", 1)
        else:
            ref_prov, ref_model = "", ref
        # A pin must be a FULL provider/model ref — a bare model id silently inherits
        # whatever provider the host resolves, which is the fail-open the policy exists
        # to close. (The org floor in opencode.model is assembled from provider+model
        # by the emit itself, so it is always full.)
        require(ref_prov == prov_id,
                f"{where}: model {ref!r} is off-provider — the org's only provider is "
                f"{prov_id!r} and a pin must name it explicitly "
                f"(a run with no explicit model inherits the host default; the policy "
                f"is enforced at definition time, not run time)")
        hit = next((b for b in banned_models if b in ref_model.lower()), None)
        require(not hit,
                f"{where}: model {ref!r} is banned by the org's model policy ({hit})")

    skills = oc.get("skills") or []
    require(isinstance(skills, list) and skills, "opencode.skills must be a non-empty list")
    unknown = [s for s in skills if s not in CANONICAL_VERBS]
    require(not unknown,
            f"opencode.skills has unknown verb(s) {sorted(unknown)}; valid: {CANONICAL_VERBS}")

    # Only-Bedrock is enforced by the ALLOWLIST (`enabled_providers`), which is the
    # only control that holds when the environment already carries ambient provider
    # keys (ANTHROPIC_API_KEY / OPENAI_API_KEY) — those get auto-detected as providers
    # that `disabled_providers: ["opencode"]` does NOT cover. The deny entry stays as
    # belt-and-suspenders (it also hides the built-in Zen provider by name).
    # Absent means "use the default"; PRESENT-but-wrong is a fail-open and must not emit.
    disabled = oc["disabled_providers"] if "disabled_providers" in oc else ["opencode"]
    require("opencode" in disabled,
            "opencode.disabled_providers must include 'opencode' — the built-in Zen "
            "provider is named explicitly, belt-and-suspenders under the allowlist")

    # The OPTIONAL supplementary reviewer (ADR 0018 §5) — the ONE surviving fresh-context
    # validator, dispatched on a COMPLETED PR, never inside the build loop. Its read
    # surface (validated read-only in graph_bindings) DERIVES the deny set the emitted
    # agent/validate.md carries; the org config's `task` rule then allowlists it and
    # subagent_depth is raised so the build agent can spawn it. When disabled, none of
    # that is emitted (agent/validate.md is dropped; task drops the validate allow).
    supp = cfg.get("supplementary_reviewer") or {}
    supp_enabled = bool(supp.get("enabled"))
    review_surface = ([str(a).lower() for a in supp.get("read_surface", [])]
                      if supp_enabled else ["read", "grep", "glob"])
    validate_deny = derived_deny(review_surface)
    for cap in ("edit", "bash", "task", "dispatch"):
        require(cap in validate_deny,
                f"supplementary_reviewer: the reviewer's derived deny set is "
                f"missing {cap!r} — a fresh-context reviewer must never keep "
                f"write/exec/delegate")

    readonly_cmds = readonly_commands(cfg["tracker"]["type"], strict=True)

    default_ref = f"{model_provider}/{model['model']}"
    small_ref = (f"{model_provider}/{model['small_model']}"
                 if model.get("small_model") else default_ref)
    # The org floor itself is validated: a banned or off-provider floor does not emit.
    check_model_ref(default_ref, "opencode.model.model")
    if model.get("small_model"):
        check_model_ref(small_ref, "opencode.model.small_model")

    # The supplementary reviewer's frontmatter model: its declared pin when enabled AND
    # set (validated on-provider + off-banned), else the org floor (the orchestration
    # model). model is OPTIONAL (ADR 0017/0018) — an unset reviewer model inherits the
    # orchestration model, NEVER the host default; a set pin is still guarded.
    if supp_enabled and supp.get("model"):
        check_model_ref(supp["model"], "supplementary_reviewer.model")
        validate_model = supp["model"]
    else:
        validate_model = default_ref
    if "/" not in validate_model:
        validate_model = f"{model_provider}/{validate_model}"
    validate_steps = str(supp["max_steps"]) if supp_enabled else "40"

    b["scalars"].update({
        "HOST_NOUN": "an opencode configuration",
        "OC_DEFAULT_MODEL_REF": default_ref,
        "OC_SMALL_MODEL_REF": small_ref,
        "OC_VALIDATE_MODEL_REF": validate_model,
        "OC_VALIDATE_STEPS": validate_steps,
        "OC_SUBAGENT_DEPTH": "2" if supp_enabled else "1",
        "OC_PROVIDER_ID": prov["id"],
        # The ORCHESTRATOR the verbs run as — never a worker (ADR 0019 §4). Default is
        # opencode's own built-in primary, which the org does not re-define.
        "OC_PRIMARY_AGENT": oc.get("primary_agent", "build"),
        # The supplementary reviewer's read-only contract, rendered into agent/validate.md:
        # one deny set (bash rendered separately as an allowlist).
        "OC_VALIDATE_DENY_LIST": ", ".join(c for c in validate_deny if c != "bash"),
        # The launcher's allowlist (ADR 0019 §4): ONLY declared workers, each with its
        # isolation. Rendered from the catalog and re-checked against it post-render.
        "OC_WORKERS_JSON": json.dumps(oc_workers_table(b["graphs"]), sort_keys=True),
    })
    mp = cfg.get("model_policy", {}) or {}
    banned = mp.get("banned", []) or []
    b["scalars"]["OC_MODEL_BANNED_JSON"] = ", ".join(json.dumps(str(x)) for x in banned)
    # The org brain loads structurally: each prime read, via the ENV-VAR path ONLY.
    # `default_local_path` is a per-person clone location — baking that machine-specific
    # absolute path into an org-wide distributed artifact is the anti-pattern (it also
    # double-loads the wiki when the env var already points at that same default). The
    # env var is the required, portable pointer; opencode skips paths that do not exist,
    # so an unset env var yields empty entries that are simply skipped.
    # A directory entry (e.g. `decisions/`) is prime's on-demand T2 read, never a preamble:
    # `instructions` loads into EVERY session, dispatched workers included (oc-06).
    reads = [r for r in (cfg["org_wiki"].get("prime_reads") or []) if not str(r).endswith("/")]
    paths = [f"{{env:{cfg['org_wiki']['local_path_env']}}}/{r}" for r in reads]
    b["arrays"].update({
        "OC_WIKI_INSTRUCTIONS": [
            {"path": pth, "comma": "" if i == len(paths) - 1 else ","}
            for i, pth in enumerate(paths)
        ],
        # `comma` carries JSON separators so the emitted opencode.json parses.
        "OC_DISABLED_PROVIDERS": [
            {"name": p, "comma": "" if i == len(disabled) - 1 else ","}
            for i, p in enumerate(disabled)
        ],
        # The validating-node deny set, one `<cap>: deny` per line; bash renders as an
        # allowlist block (tracker reads + SCM reads), not a `bash: deny` line.
        "OC_VALIDATE_DENY": [{"cap": c} for c in validate_deny if c != "bash"],
        "OC_READONLY_BASH": [{"pattern": p} for p in readonly_cmds],
    })
    # /triage is a command over a folded skill: a declared triage worker needs the skill
    # folded, and a folded triage skill needs a worker to launch (else a dead verb).
    triage_on = b["conditionals"]["TRIAGE_ENABLED"]
    require(triage_on == ("triage" in skills),
            "opencode.skills must list `triage` exactly when a worker graph binds the "
            "triage verb — command/triage.md reads skill/triage/SKILL.md, which launches it "
            f"(triage worker declared: {triage_on}; in opencode.skills: {'triage' in skills})")
    b["conditionals"] = {"TARGET_CC": False, "TARGET_OPENCODE": True,
                         "SUPP_REVIEWER_ENABLED": supp_enabled, "TRIAGE_ENABLED": triage_on}
    return b


def rename_verbs(out: Path, verbs: dict, skills_dir: str = "skills",
                 agents_dir: str | None = "agents",
                 commands_dir: str | None = None) -> int:
    """Rename emitted skill dirs / commands to the org's verbs.

    The templates ship canonical (skills/inception); the org's `name:` frontmatter is
    already org-rendered via {{VERB_*}}, so the invocable name is correct regardless —
    but renaming the paths keeps the OUTPUT tidy and matching. Shared by every target;
    only the host's directory nouns differ.

    `agents_dir=None` skips the (legacy) gate-agent rename. Under ADR 0018 there is no
    gate AGENT to rename on either target — the gate is a rubric the build agent applies,
    not a dispatchable agent — so the gate branch below is a no-op when no agents/gate.md
    exists.
    """
    renames = 0
    for canon, name in verbs.items():
        if name == canon:
            continue
        sd = out / skills_dir / canon
        if sd.is_dir():
            sd.rename(out / skills_dir / name)
            renames += 1
        if commands_dir:
            cf = out / commands_dir / f"{canon}.md"
            if cf.is_file():
                cf.rename(out / commands_dir / f"{name}.md")
                renames += 1
    # the gate verb is also an agent file (on hosts that name agents by verb)
    gate_name = verbs["gate"]
    if agents_dir and gate_name != "gate":
        gf = out / agents_dir / "gate.md"
        if gf.is_file():
            gf.rename(out / agents_dir / f"{gate_name}.md")
            renames += 1
    return renames


def org_strings(cfg) -> set[str]:
    """Every string the org wrote in its config — its own identity is never a leak."""
    out = set()
    def walk(v):
        if isinstance(v, str):
            out.add(v)
        elif isinstance(v, dict):
            for x in v.values(): walk(x)
        elif isinstance(v, list):
            for x in v: walk(x)
    walk(cfg)
    return out


def _frontmatter(path: Path) -> dict:
    txt = path.read_text()
    require(txt.startswith("---"), f"{path.name}: no frontmatter")
    return yaml.safe_load(txt.split("---", 2)[1]) or {}


def assert_worker_contract(path: Path, g: dict, verbs: dict, target: str) -> None:
    """Post-render, on the ARTIFACT: the emitted worker is its own identity, capped by
    the host, and cannot fan out (ADR 0019 §4-5). A template edit that breaks any of
    these fails the emit — it is not left to a test that nobody re-runs."""
    fm = _frontmatter(path)
    cap = g["max_total_steps"]
    if target == "claude-code":
        pre = fm.get("skills") or []
        leaked = sorted(set(pre) & set(verbs.values()))
        require(not leaked,
                f"agents/{g['agent']}.md preloads verb skill(s) {leaked} — a worker preloads "
                f"only its graph index + entry node, never an orchestrator verb (ADR 0019 §4)")
        require(index_skill(g) in pre,
                f"agents/{g['agent']}.md does not preload its graph index {index_skill(g)!r}")
        require(fm.get("maxTurns") == cap,
                f"agents/{g['agent']}.md maxTurns is {fm.get('maxTurns')!r}, not the graph's "
                f"max_total_steps {cap} — the cap must be host-enforced")
        tools = [t.strip() for t in str(fm.get("tools", "")).split(",") if t.strip()]
        fan = sorted({"Agent", "Skill", "Task", "Workflow"} & set(tools))
        require(not fan, f"agents/{g['agent']}.md carries fan-out tool(s) {fan}")
    else:
        require(fm.get("steps") == cap,
                f"agent/{g['agent']}.md steps is {fm.get('steps')!r}, not the graph's "
                f"max_total_steps {cap} — the cap must be host-enforced")
        perm = fm.get("permission") or {}
        open_ = [c for c in OC_WORKER_ALWAYS_DENY if perm.get(c) != "deny"]
        require(not open_,
                f"agent/{g['agent']}.md does not deny {open_} — a worker never dispatches, "
                f"spawns or asks the human (ADR 0019 §4)")
        rules = list(perm.items())
        want = oc_mcp_rules(g)
        require([r for r in rules if r in want] == want,
                f"agent/{g['agent']}.md does not carry its MCP permission rules in order "
                f"{want} — a denied MCP tool (e.g. {ENV_SWITCH_TOOL}) would stay callable")
    if target == "claude-code":
        tools = {t.strip() for t in str(fm.get("tools", "")).split(",") if t.strip()}
        denied = {t.strip() for t in str(fm.get("disallowedTools", "")).split(",")}
        missing = sorted(d for d in g.get("deny", []) if d in tools or d not in denied)
        require(not missing,
                f"agents/{g['agent']}.md grants or fails to disallow denied tool(s) {missing}")


def render_worker_agents(bindings: dict, cfg: dict, out: Path, agents_dir: str,
                         target: str) -> list[Path]:
    """The per-graph render loop (ADR 0019): each WORKER graph's own body template
    (templates/graphs/<graph>/agent.md.template) renders once, with that graph's
    bindings, to <agents_dir>/<agent>.md. A worker graph with no body template does not
    emit — the catalog would otherwise validate a graph no host can run."""
    rendered = []
    for g in bindings["graphs"]:
        if g["launch"] != "worker":
            continue
        tpl = GRAPHS_DIR / g["name"] / "agent.md.template"
        require(tpl.is_file(),
                f"graphs.{g['name']}: a worker graph needs its own body template "
                f"(templates/graphs/{g['name']}/agent.md.template) — none exists")
        dest = render_file(
            graph_bindings(bindings, g, target), tpl,
            out / agents_dir / f"{g['agent']}.md", FORGE_ROOT,
            leak_check=True, leak_allow=org_strings(cfg))
        assert_worker_contract(dest, g, bindings["verbs"], target)
        if target == "opencode":  # the opencode body inlines the node walk (no preloads)
            assert_node_refs(dest, node_lines(g, target, bindings["verbs"]), out, target)
        rendered.append(dest)
    return rendered


def render_node_file(bindings: dict, template: Path, dest: Path, allow: set) -> Path:
    """Render a skill template as a plain path-read file: same guards as a skill, minus
    the skill frontmatter (a file is read by path, never listed or invoked)."""
    render_file(bindings, template, dest, FORGE_ROOT, leak_check=True, leak_allow=allow)
    txt = dest.read_text()
    if txt.startswith("---"):
        dest.write_text(txt.split("---", 2)[2].lstrip("\n"))
    return dest


def assert_node_refs(path: Path, lines: list[dict], out: Path, target: str) -> None:
    """Post-render, on the ARTIFACT: every node path a graph index (or an opencode worker
    body) names is spelled in it and resolves in the emitted tree. A dangling reference
    fails the emit — the walker would enter a node it cannot read."""
    text, where = path.read_text(), path.relative_to(out)
    for item in lines:
        ref = _node_ref(item["path"], target)
        require(f"`{ref}`" in text, f"{where} does not name its node path `{ref}`")
        require((out / item["path"]).is_file(),
                f"{where}: node reference `{ref}` is dangling — {item['path']} was not "
                f"emitted")


def foreign_mcp_patterns(graphs: list[dict], target: str) -> list[re.Pattern]:
    """What an emitted file on `target` may NEVER spell (TEC-4099): the OTHER host's name
    for any declared server's tools (and the server's name as forge renders it, in
    backticks), or an unresolved handle. Built from each graph's per-target map."""
    edge = r"(?<![\w.-]){}(?![\w.-])"
    pats = []
    for g in graphs:
        for h, per in g.get("mcp_by_target", {}).items():
            mine, cc, oc = per.get(target), per.get("claude-code"), per.get("opencode")
            if target == "opencode":
                pats += [re.escape(f"mcp__{x}__") for x in {h, cc, oc} if x]
            elif h != cc:
                pats.append(re.escape(f"mcp__{h}__"))
            other = oc if target == "claude-code" else cc
            if not other:
                continue
            if other != mine:
                pats.append(re.escape(f"`{other}`"))
                if target == "opencode" and other.startswith("plugin_"):
                    # a Claude Code plugin-server name is never an opencode key, bare or not
                    pats.append(edge.format(re.escape(other)))
            if target == "claude-code":
                pats += [edge.format(re.escape(oc_tool_key(oc, t)))
                         for t in g["mcp_tools"][h]]
    return [re.compile(p) for p in sorted(set(pats))]


def assert_host_native_mcp(out: Path, graphs: list[dict], target: str) -> None:
    """Post-render, on the ARTIFACT: no emitted file names a declared MCP server's tools
    the way the OTHER host spells them (a Claude Code name on opencode, an opencode key on
    Claude Code) — that tool would not exist on this host, and a read_only worker's wall
    would be keyed to nothing. The whole out tree is this emit's (render_tree wipes it)."""
    pats = foreign_mcp_patterns(graphs, target)
    if not pats:
        return
    for f in sorted(p for p in out.rglob("*") if p.is_file()):
        try:
            text = f.read_text()
        except UnicodeDecodeError:
            continue
        for pat in pats:
            m = pat.search(text)
            require(m is None,
                    f"{f.relative_to(out)} names {m.group(0) if m else ''!r} — another "
                    f"host's spelling of a declared MCP server/tool; on {target} each file "
                    f"must name only {target}'s server names (mcp_servers.<handle>.{target})")


def render_graph_skills(bindings: dict, cfg: dict, out: Path, skills_dir: str,
                        target: str) -> list[Path]:
    """Every graph's T1 index and every node skill a graph binds (rendered once each).
    Only a worker's preloads — its index + entry node — are skills (<skills_dir>/); every
    other node, and a main_thread graph's index, is a path-read file in the node dir
    (TEC-4098). Verb skills are rendered by the verb pass, not here. Each index's node
    paths are then checked against the emitted tree."""
    rendered, seen, indexes = [], set(), []
    allow = org_strings(cfg)
    verbs = bindings["verbs"]
    files = out / NODE_DIRS[target]
    for g in bindings["graphs"]:
        gb = graph_bindings(bindings, g, target)
        tpl = GRAPHS_DIR / "index" / "SKILL.md.template"
        if g["launch"] == "worker":
            idx = render_file(gb, tpl, out / skills_dir / index_skill(g) / "SKILL.md",
                              FORGE_ROOT, leak_check=True, leak_allow=allow)
        else:
            idx = render_node_file(gb, tpl, files / f"{index_skill(g)}.md", allow)
        rendered.append(idx)
        indexes.append((idx, gb["arrays"]["GRAPH_NODES"]))
        for name, node in g["nodes"].items():
            if "skill" not in node or node["skill"] in verbs:
                continue
            tpl = NODE_SKILLS_DIR / node["skill"] / "SKILL.md.template"
            if node_is_skill(g, name, verbs):
                dest = out / skills_dir / node["skill"] / "SKILL.md"
                if dest not in seen:
                    rendered.append(render_file(bindings, tpl, dest, FORGE_ROOT,
                                                leak_check=True, leak_allow=allow))
            else:
                dest = files / f"{node['skill']}.md"
                if dest not in seen:
                    rendered.append(render_node_file(bindings, tpl, dest, allow))
            seen.add(dest)
    for idx, lines in indexes:
        assert_node_refs(idx, lines, out, target)
    return rendered


def drop_unbound_triage(path: Path, bindings: dict, rendered: list[Path]) -> list[Path]:
    """Remove the triage verb's rendered entry (a skill dir or a command file) when no
    worker graph binds the verb — a /triage with no worker to launch is a dead verb."""
    if bindings["conditionals"]["TRIAGE_ENABLED"] or not path.exists():
        return rendered
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return [p for p in rendered if p != path and path not in p.parents]


def emit_claude_code(cfg: dict, out: Path):
    """Target: a Claude Code plugin (skills/ + agents/ + hooks/ + .claude-plugin/)."""
    bindings = build_bindings(cfg)
    rendered = render_tree(
        bindings,
        FORGE_ROOT / "templates/org-plugin",
        out,
        FORGE_ROOT,
        leak_check=True, leak_allow=org_strings(cfg),
    )
    renames = rename_verbs(out, resolve_verbs(cfg))
    # skills/<triage> launches the triage worker — kept ONLY when a worker binds the verb.
    rendered = drop_unbound_triage(out / "skills" / bindings["verbs"]["triage"], bindings,
                                   rendered)
    # agents/validate.md — the supplementary reviewer — is kept ONLY when enabled.
    validate_agent = out / "agents" / "validate.md"
    if not bindings["conditionals"]["SUPP_REVIEWER_ENABLED"] and validate_agent.is_file():
        validate_agent.unlink()
        rendered = [p for p in rendered if p != validate_agent]
    rendered += render_graph_skills(bindings, cfg, out, "skills", "claude-code")
    rendered += render_worker_agents(bindings, cfg, out, "agents", "claude-code")
    assert_host_native_mcp(out, bindings["graphs"], "claude-code")
    return rendered, renames


def emit_opencode(cfg: dict, out: Path):
    """Target: an opencode configuration (opencode.json + agent/ + command/ + skill/).

    Two passes. Pass 1 renders the opencode-specific packaging. Pass 2 folds the SHARED
    skill bodies (the same templates the Claude Code target renders) into skill/<verb>/,
    so a skill's prose is byte-identical across targets except where a {{#TARGET_*}}
    conditional or a host-noun scalar deliberately differs.
    """
    bindings = build_bindings_opencode(cfg)
    rendered = render_tree(
        bindings,
        FORGE_ROOT / "templates/opencode",
        out,
        FORGE_ROOT,
        leak_check=True, leak_allow=org_strings(cfg),
        clean=True,
    )
    for canon in cfg["opencode"]["skills"]:
        src = FORGE_ROOT / "templates/org-plugin/skills" / canon
        require(src.is_dir(), f"opencode.skills: no shared skill template for '{canon}'")
        rendered += render_tree(
            bindings, src, out / "skill" / canon, FORGE_ROOT,
            leak_check=True, clean=False, leak_allow=org_strings(cfg),
        )
    # command/ and skill/ ARE verb-named; agent/ carries one file per worker graph plus
    # the OPTIONAL supplementary reviewer (agent/validate.md) — fixed names, not verbs.
    renames = rename_verbs(out, resolve_verbs(cfg), skills_dir="skill",
                           agents_dir=None, commands_dir="command")
    rendered = drop_unbound_triage(out / "command" / f"{bindings['verbs']['triage']}.md",
                                   bindings, rendered)
    # The graphs (ADR 0019): the rubrics (opencode ships them too, under rubric/), each
    # graph's index + node skills (skill/), and each worker graph's own agent file.
    rendered += render_tree(bindings, RUBRICS_DIR, out / "rubric", FORGE_ROOT,
                            leak_check=True, clean=False, leak_allow=org_strings(cfg))
    rendered += render_graph_skills(bindings, cfg, out, "skill", "opencode")
    rendered += render_worker_agents(bindings, cfg, out, "agent", "opencode")
    sc = bindings["scalars"]
    supp_enabled = bindings["conditionals"].get("SUPP_REVIEWER_ENABLED", False)

    # agent/validate.md always renders (render_tree renders every *.template); it is the
    # supplementary reviewer's contract, kept ONLY when the reviewer is enabled. When it
    # is disabled there is no fresh-context validator to emit — drop the file.
    validate_agent = out / "agent" / "validate.md"
    if not supp_enabled and validate_agent.is_file():
        validate_agent.unlink()
        rendered = [p for p in rendered if p != validate_agent]

    # Post-render assertions on the artifact itself, not on the config.
    conf = json.loads((out / "opencode.json").read_text())
    require(conf.get("enabled_providers") == [sc["OC_PROVIDER_ID"]],
            f"opencode.json enabled_providers must be exactly "
            f"[{sc['OC_PROVIDER_ID']!r}] — the allowlist is the only-Bedrock "
            f"control that survives an ambient ANTHROPIC_API_KEY/OPENAI_API_KEY "
            f"(got {conf.get('enabled_providers')!r})")

    # The `task` allowlist: '*': deny is NON-NEGOTIABLE (the orchestrator's only door to a
    # child run stays denied-by-default), and the primary build agent is allowlisted. The
    # `validate` allow + subagent_depth>=2 are GATED on the supplementary reviewer being
    # enabled — only then can the build agent spawn a fresh-context reviewer as a subagent.
    task_perm = (conf.get("permission") or {}).get("task")
    require(isinstance(task_perm, dict)
            and task_perm.get("*") == "deny"
            and task_perm.get(sc["OC_PRIMARY_AGENT"]) == "allow",
            f"opencode.json permission.task must be a '*': deny allowlist with "
            f"{sc['OC_PRIMARY_AGENT']!r} allowed — got {task_perm!r}")
    if supp_enabled:
        require(int(conf.get("subagent_depth", 1)) >= 2,
                f"opencode.json subagent_depth must be >= 2 when the supplementary "
                f"reviewer is enabled — the build agent (depth 1) spawns it as a native "
                f"subagent (depth 2) (got {conf.get('subagent_depth')!r})")
        require(validate_agent.is_file(),
                "agent/validate.md — the supplementary reviewer's contract — was not "
                "rendered though the reviewer is enabled")
        require(task_perm.get("validate") == "allow",
                f"opencode.json permission.task must allow 'validate' when the "
                f"supplementary reviewer is enabled — got {task_perm!r}")
    else:
        require(task_perm.get("validate") != "allow",
                "opencode.json permission.task allows 'validate' but the supplementary "
                "reviewer is disabled — a spawnable reviewer with no contract file")

    # Distinct identities (ADR 0019 §4): the orchestrator is never a worker, and no
    # worker is spawnable through the native task tool (it would land in the
    # orchestrator's location instead of its own worktree).
    workers = oc_workers_table(bindings["graphs"])
    require(conf.get("default_agent") not in workers,
            f"opencode.json default_agent {conf.get('default_agent')!r} is a worker — the "
            f"orchestrator and a worker never share a definition")
    spawnable = sorted(w for w in workers if task_perm.get(w) == "allow")
    require(not spawnable, f"opencode.json permission.task allows worker(s) {spawnable}")
    # The launcher's allowlist, read back from the artifact: exactly the catalog.
    src = (out / "plugin" / "dispatch.js").read_text()
    m = re.search(r"^const WORKERS = (\{.*\})$", src, re.M)
    require(m is not None and json.loads(m.group(1)) == workers,
            f"plugin/dispatch.js WORKERS table does not match the catalog's workers "
            f"{workers} — dispatch would launch an undeclared agent or the wrong isolation")
    assert_host_native_mcp(out, bindings["graphs"], "opencode")
    return rendered, renames


TARGETS = {
    "claude-code": emit_claude_code,
    "opencode": emit_opencode,
}


# --- opencode host version ------------------------------------------------------------
# The emitted configuration is ONE artifact for TWO hosts (the emitted plugins carry
# both entrypoints: 2.x loads setup(), 1.18.29+ loads server()). The floor is 1.18.29
# — the first 1.x release that accepts the object form with server(). Older hosts can
# only run the pre-dual releases of an org's emitted package.
OPENCODE_FLOOR = (1, 18, 29)


def parse_opencode_version(text: str) -> tuple[int, int, int] | None:
    """`opencode v2.0.8` / `opencode 1.18.29` → (2, 0, 8) / (1, 18, 29)."""
    m = re.search(r"v?(\d+)\.(\d+)\.(\d+)", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def opencode_host_version() -> tuple[int, int, int] | None:
    """The installed opencode's version, or None when it is not on PATH."""
    try:
        out = subprocess.run(["opencode", "--version"], capture_output=True,
                             text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return parse_opencode_version(out.stdout or "")


def check_opencode_host():
    """Warn or fail against the opencode actually installed where we emit.

    The artifact is the same either way (dual entrypoint); this only guards the
    floor and tells the operator which half will run on their host.
    """
    v = opencode_host_version()
    if v is None:
        print("opencode: not found on PATH — the artifact targets opencode "
              f">={'.'.join(map(str, OPENCODE_FLOOR))} and 2.x (both entrypoints)")
        return
    pretty = ".".join(map(str, v))
    if v < OPENCODE_FLOOR:
        raise SystemExit(
            f"emit: detected opencode v{pretty} — the emitted plugins' 1.x entrypoint "
            f"(server()) needs opencode >={'.'.join(map(str, OPENCODE_FLOOR))}. "
            "Upgrade opencode, or keep the previously emitted package.")
    half = "setup() (2.x)" if v >= (2, 0, 0) else "server() (1.18.29+)"
    print(f"opencode v{pretty} detected — artifact carries both entrypoints; "
          f"this host loads {half}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="forge emit driver")
    ap.add_argument("--config", default=".forge.org.yaml")
    ap.add_argument("--out", required=True)
    ap.add_argument("--target", default="claude-code", choices=sorted(TARGETS),
                    help="host to emit for (default: claude-code)")
    args = ap.parse_args(argv)

    cfg = yaml.safe_load(Path(args.config).read_text())
    out = Path(args.out)
    rendered, renames = TARGETS[args.target](cfg, out)

    print(f"OK emitted {cfg['plugin']['name']} v{cfg['plugin']['version']} "
          f"→ {args.out} ({len(rendered)} files, {renames} verb renames)")
    print("leak gate: clean (no generator identity in output)")
    if args.target == "opencode":
        check_opencode_host()


if __name__ == "__main__":
    main()
