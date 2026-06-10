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
A snippet resolves to a scalar: the first fenced code block under the adapter
heading ``### `<label>` `` (optionally `— …`), with its `vars` substituted.
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


def extract_snippet(adapter_text: str, label: str, snippet_vars: dict) -> str:
    """First fenced code block under ``### `<label>` `` in an adapter file."""
    heading = re.compile(
        r"^#{2,4}\s+`%s`.*?$" % re.escape(label), re.M)
    m = heading.search(adapter_text)
    if not m:
        raise SystemExit(f"snippet label `{label}` not found in adapter")
    rest = adapter_text[m.end():]
    fence = re.search(r"```[a-zA-Z0-9_-]*\n(.*?)\n```", rest, re.S)
    if not fence:
        raise SystemExit(f"no fenced block under `{label}` in adapter")
    body = fence.group(1)
    for k, v in (snippet_vars or {}).items():
        body = body.replace("{{%s}}" % k, str(v))
    return body


def resolve_snippets(bindings: dict, forge_root: Path) -> dict:
    """Fold snippet specs into the scalar map (placeholder → extracted text)."""
    scalars = dict(bindings.get("scalars", {}))
    for spec in bindings.get("snippets", []):
        adapter_text = (forge_root / spec["adapter"]).read_text()
        scalars[spec["placeholder"]] = extract_snippet(
            adapter_text, spec["label"], spec.get("vars", {}))
    return scalars


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


def render_tree(bindings: dict, templates_dir: Path, out_dir: Path,
                forge_root: Path, leak_check: bool = False) -> list[Path]:
    """Render every *.template under templates_dir into out_dir. Returns paths."""
    scalars = resolve_snippets(bindings, forge_root)
    arrays = bindings.get("arrays", {})
    conditionals = bindings.get("conditionals", {})

    if out_dir.exists():
        shutil.rmtree(out_dir)
    rendered = []
    for tpl in sorted(templates_dir.rglob("*.template")):
        rel = tpl.relative_to(templates_dir)
        dest = out_dir / rel.with_suffix("")  # drop .template
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = tpl.read_text()
        text = _render_arrays(text, arrays)
        text = _render_conditionals(text, conditionals)
        text = _render_scalars(text, scalars)
        dest.write_text(text)
        rendered.append(dest)

    # No unresolved placeholders may survive.
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
        leaks = []
        for d in rendered:
            for i, line in enumerate(d.read_text().splitlines(), 1):
                if LEAK_RE.search(line):
                    leaks.append(f"{d.relative_to(out_dir)}:{i}: {line.strip()}")
        if leaks:
            print("LEAK GATE TRIPPED — generator identity in emitted package:", file=sys.stderr)
            print("\n".join("  " + l for l in leaks), file=sys.stderr)
            raise SystemExit(3)

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
