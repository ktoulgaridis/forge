#!/usr/bin/env python3
"""forge's shared template-rendering engine.

The single deterministic renderer behind BOTH generative commands:
  - /forge:new  → renders templates/wiki/      (project tier)
  - /forge:emit → renders templates/org-plugin/ (org tier)

Each command computes a `bindings` object from its own config tier and calls
`render_tree(...)`. The mechanics — scalar substitution, array repeats,
conditional sections, adapter-snippet inlining, the unresolved-placeholder
assertion, and the optional identity leak gate — live here, once.

Dependency-free (stdlib only) so it runs under `uv run python lib/render.py`
with no environment to provision.

bindings schema (JSON):
{
  "scalars":      { "PLACEHOLDER": "value", ... },
  "arrays":       { "NAME": [ "scalar" | {"field": "v", ...}, ... ], ... },
  "conditionals": { "dotted.name": true|false, ... },
  "snippets":     [ { "placeholder": "TRACKER_PRIME_SNIPPET",
                      "adapter": "adapters/tracker/jira-mcp.md",
                      "label": "TRACKER_PRIME_SNIPPET",
                      "vars": { "tracker.config.cloud_id": "..." } }, ... ]
}
A snippet is the first fenced code block under the adapter heading ``### `<label>` ``
(optionally `— …`), with its `vars` (and the scalars) substituted. It renders as ONE
fenced block: a template that already fenced the placeholder keeps its fence.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

# What the leak gate forbids in EMITTED output: the generator's identity.
# Word-boundary on "forge" so legitimate English ("fire-and-forget") is fine.
LEAK_RE = re.compile(r"\bforge\b|ktoulgaridis|toulgaridis", re.I)


def _snippet_fence(adapter_text: str, label: str) -> tuple[str, str]:
    """(language, body) of the first fenced code block under ``### `<label>` ``."""
    heading = re.compile(
        r"^#{2,4}\s+`%s`.*?$" % re.escape(label), re.M)
    m = heading.search(adapter_text)
    if not m:
        raise SystemExit(f"snippet label `{label}` not found in adapter")
    rest = adapter_text[m.end():]
    fence = re.search(r"```([a-zA-Z0-9_-]*)\n(.*?)\n```", rest, re.S)
    if not fence:
        raise SystemExit(f"no fenced block under `{label}` in adapter")
    return fence.group(1), fence.group(2)


def _substitute(body: str, snippet_vars: dict, scalars: dict | None = None) -> str:
    for k, v in (snippet_vars or {}).items():
        body = body.replace("{{%s}}" % k, str(v))
    # The org's own scalars (e.g. its verb names) reach the snippet text too, so an
    # adapter can say {{VERB_REFINE}}→{{VERB_EXECUTE}} and survive a verb rename.
    for k, v in (scalars or {}).items():
        body = body.replace("{{%s}}" % k, str(v))
    return body


def extract_snippet(adapter_text: str, label: str, snippet_vars: dict) -> str:
    """The BODY of the first fenced code block under ``### `<label>` `` (no fence) —
    for callers that parse it (e.g. the read-only command allowlist)."""
    return _substitute(_snippet_fence(adapter_text, label)[1], snippet_vars)


def resolve_snippets(bindings: dict, forge_root: Path) -> tuple[dict, dict]:
    """(scalars, snippets): the scalar map, and each snippet placeholder → (lang, body)."""
    scalars = dict(bindings.get("scalars", {}))
    snippets = {}
    for spec in bindings.get("snippets", []):
        adapter_text = (forge_root / spec["adapter"]).read_text()
        lang, body = _snippet_fence(adapter_text, spec["label"])
        snippets[spec["placeholder"]] = (
            lang or "bash", _substitute(body, spec.get("vars", {}), scalars))
    return scalars, snippets


def _indent(body: str, ind: str) -> str:
    return "\n".join(ind + ln if ln else ln for ln in body.split("\n"))


def _render_snippets(text: str, snippets: dict) -> str:
    """Inline each snippet as a fenced code block, exactly once:
    - a placeholder a template ALREADY fenced keeps that one fence (idempotent);
    - a placeholder alone on its line gets a fence, indented like the placeholder (so a
      snippet inside a list item stays inside it);
    - anything else (mid-line) gets the bare body."""
    for name, (lang, body) in snippets.items():
        ph = re.escape("{{%s}}" % name)
        pre = re.compile(r"^([ \t]*)(```[^\n]*)\n[ \t]*%s[ \t]*\n([ \t]*```)" % ph, re.M)
        text = pre.sub(lambda m: f"{m.group(1)}{m.group(2)}\n{_indent(body, m.group(1))}\n"
                                 f"{m.group(3)}", text)
        own = re.compile(r"^([ \t]*)%s[ \t]*$" % ph, re.M)
        text = own.sub(lambda m: f"{m.group(1)}```{lang}\n{_indent(body, m.group(1))}\n"
                                 f"{m.group(1)}```", text)
        text = text.replace("{{%s}}" % name, body)
    return text


def _render_arrays(text: str, arrays: dict) -> str:
    for name, items in arrays.items():
        pat = re.compile(r"\{\{#%s\}\}\n?(.*?)\{\{/%s\}\}\n?" % (name, name), re.S)

        def repl(m, items=items):
            body = m.group(1)
            out = []
            for it in items:
                chunk = body
                if isinstance(it, dict):
                    for f, v in it.items():
                        chunk = chunk.replace("{{%s}}" % f, str(v))
                else:
                    chunk = chunk.replace("{{.}}", str(it))
                out.append(chunk)
            return "".join(out)

        text = pat.sub(repl, text)
    return text


def _render_conditionals(text: str, conditionals: dict) -> str:
    for name, keep in conditionals.items():
        pat = re.compile(r"\{\{#%s\}\}\n?(.*?)\{\{/%s\}\}\n?" % (re.escape(name), re.escape(name)), re.S)
        text = pat.sub((lambda m: m.group(1)) if keep else (lambda m: ""), text)
    return text


def _render_scalars(text: str, scalars: dict) -> str:
    for k, v in scalars.items():
        text = text.replace("{{%s}}" % k, str(v))
    return text


def _render_text(text: str, scalars: dict, arrays: dict, conditionals: dict,
                 snippets: dict | None = None) -> str:
    text = _render_arrays(text, arrays)
    text = _render_conditionals(text, conditionals)
    text = _render_snippets(text, snippets or {})
    return _render_scalars(text, scalars)


def _check_rendered(rendered: list[Path], out_dir: Path, leak_check: bool,
                    leak_allow: set[str] | None) -> None:
    """No unresolved placeholders may survive; with leak_check, no generator identity."""
    unresolved = []
    for d in rendered:
        for m in re.finditer(r"\{\{[^}]+\}\}", d.read_text()):
            unresolved.append(f"{d.relative_to(out_dir)}: {m.group(0)}")
    if unresolved:
        print("UNRESOLVED PLACEHOLDERS:", file=sys.stderr)
        print("\n".join("  " + u for u in unresolved), file=sys.stderr)
        raise SystemExit(2)

    # Leak gate: zero generator identity in emitted output (emit only).
    if leak_check:
        allowed = [a.lower() for a in (leak_allow or set())]
        leaks = []
        for d in rendered:
            for i, line in enumerate(d.read_text().splitlines(), 1):
                hit = LEAK_RE.search(line)
                low = line.lower()
                if hit and not any(hit.group(0).lower() in a and a in low for a in allowed):
                    leaks.append(f"{d.relative_to(out_dir)}:{i}: {line.strip()}")
        if leaks:
            print("LEAK GATE TRIPPED — generator identity in emitted package:", file=sys.stderr)
            print("\n".join("  " + l for l in leaks), file=sys.stderr)
            raise SystemExit(3)


def render_file(bindings: dict, template: Path, dest: Path, forge_root: Path,
                leak_check: bool = False, leak_allow: set[str] | None = None) -> Path:
    """Render ONE template to ONE destination (the per-graph render loop: a graph's body
    template renders once per graph, with that graph's bindings). Same guards as
    render_tree: no unresolved placeholder, and the optional leak gate."""
    scalars, snippets = resolve_snippets(bindings, forge_root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(_render_text(template.read_text(), scalars,
                                 bindings.get("arrays", {}),
                                 bindings.get("conditionals", {}), snippets))
    _check_rendered([dest], dest.parent, leak_check, leak_allow)
    return dest


def render_tree(bindings: dict, templates_dir: Path, out_dir: Path,
                forge_root: Path, leak_check: bool = False,
                clean: bool = True, leak_allow: set[str] | None = None) -> list[Path]:
    """Render every *.template under templates_dir into out_dir. Returns paths.

    `clean` (default True) wipes out_dir first — the behaviour every single-pass
    render wants. A multi-pass emitter (one that folds a SHARED template tree into
    a subdirectory of an already-rendered target tree) passes clean=False so the
    second pass does not delete the first pass's output.

    `leak_allow`: strings that are the ORG's own (its config values). A token the gate
    would flag is not a leak when the org itself spelled it — the maintainer's own org
    is a legitimate org, and an org may track work in a repo called forge.
    """
    scalars, snippets = resolve_snippets(bindings, forge_root)
    arrays = bindings.get("arrays", {})
    conditionals = bindings.get("conditionals", {})

    if clean and out_dir.exists():
        shutil.rmtree(out_dir)
    rendered = []
    for tpl in sorted(templates_dir.rglob("*.template")):
        rel = tpl.relative_to(templates_dir)
        dest = out_dir / rel.with_suffix("")  # drop .template
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(_render_text(tpl.read_text(), scalars, arrays, conditionals, snippets))
        rendered.append(dest)

    _check_rendered(rendered, out_dir, leak_check, leak_allow)
    return rendered


def main(argv=None):
    ap = argparse.ArgumentParser(description="forge shared template renderer")
    ap.add_argument("--bindings", required=True, help="path to bindings JSON")
    ap.add_argument("--templates", required=True, help="template tree to render")
    ap.add_argument("--out", required=True, help="destination directory")
    ap.add_argument("--forge-root", default=str(Path(__file__).resolve().parent.parent),
                    help="forge repo root (for resolving adapter snippet paths)")
    ap.add_argument("--leak-check", action="store_true",
                    help="fail if generator identity appears in the output")
    args = ap.parse_args(argv)

    bindings = json.loads(Path(args.bindings).read_text())
    rendered = render_tree(
        bindings, Path(args.templates), Path(args.out),
        Path(args.forge_root), leak_check=args.leak_check)

    print(f"OK rendered {len(rendered)} files to {args.out}")
    if args.leak_check:
        print("leak gate: clean (no generator identity in output)")
    for d in rendered:
        print("  " + str(d.relative_to(Path(args.out))))


if __name__ == "__main__":
    main()
