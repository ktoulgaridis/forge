// Behavioural harness for the emitted opencode `dispatch` tool family.
// Loads a RENDERED plugin file, hands it a fake host, runs ONE call (or a
// sequence) against a REAL temp git workspace, and prints what happened as JSON.
//
// The emitted plugin carries BOTH host entrypoints (back/forward compatibility):
//   host v1 — opencode 1.18.29+: `server({client})` returns the 1.x hooks; tools
//             execute with a per-call ctx. The 1.x SDK is shimmed next to the plugin.
//   host v2 — opencode 2.x: `setup(ctx)` registers the tools through a transform;
//             sessions are created/prompted/waited/read through the ctx client.
//
// A call may name a different tool in the same plugin instance via `_tool`
// (e.g. {"_tool": "dispatch_read", "task_id": "ses_1"}); it defaults to `dispatch`.
//
// usage: node dispatch_harness.mjs <plugin.js> <workspace-dir> '<args-json>' [host]
import { pathToFileURL } from "node:url"

const [, , pluginPath, workspace, argsJson, hostArg] = process.argv
const host = hostArg === "v2" ? "v2" : "v1"
const calls = []
const nCreates = () => calls.filter((c) => c.op === "create").length

// The rendered plugin imports `@opencode-ai/plugin` dynamically inside server() (a 2.x
// host never resolves it). Shim just what the 1.x tool helper offers: tool() + a
// chainable schema builder.
import { mkdirSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"
const shimDir = join(dirname(pluginPath), "node_modules", "@opencode-ai", "plugin")
mkdirSync(shimDir, { recursive: true })
writeFileSync(join(shimDir, "package.json"), JSON.stringify({ name: "@opencode-ai/plugin", type: "module", main: "index.js" }))
writeFileSync(join(shimDir, "index.js"), `
const chain = () => { const c = {}; for (const k of ["optional","describe","default"]) c[k] = () => c; return c }
export const tool = (input) => input
tool.schema = { string: chain, boolean: chain, number: chain }
`)

// 1.x client: methods return {data} / {error}.
const v1client = {
  session: {
    create: async (input) => {
      calls.push({ op: "create", input })
      if (process.env.HARNESS_FAIL === "create") return { error: { name: "ProviderError", message: "boom" } }
      return { data: { id: `ses_${nCreates()}` } }
    },
    prompt: async (input) => {
      calls.push({ op: "prompt", input })
      if (process.env.HARNESS_FAIL === "prompt") return { error: { name: "NotFoundError", message: "no such session" } }
      return { data: { info: {}, parts: [{ type: "text", text: "PR https://x/pr/1 opened" }] } }
    },
    promptAsync: async (input) => {
      calls.push({ op: "promptAsync", input })
      return { data: {} }
    },
  },
}

// 2.x ctx: methods return the data directly and THROW on failure.
const registered = {}
const v2ctx = {
  location: { directory: workspace },
  tool: { transform: async (fn) => { await fn({ add: (t) => { registered[t.name] = t } }) } },
  session: {
    create: async (input) => {
      calls.push({ op: "create", input })
      if (process.env.HARNESS_FAIL === "create") throw new Error("boom")
      return { id: `ses_${nCreates()}` }
    },
    prompt: async (input) => {
      calls.push({ op: "prompt", input })
      // The postback is now a prompt to the parent with resume:false (no more synthetic).
      // A WORKER-directed failure must not also kill the parent postback — model the worker
      // failing while the <run-closed> line still reaches the orchestrator.
      if (process.env.HARNESS_FAIL === "prompt" && input.sessionID !== "ses_parent") throw new Error("no such session")
      return { info: {} }
    },
    wait: async (input) => {
      calls.push({ op: "wait", input })
      // The prompt's failure surfaces at wait (the run died) — a closing postback that
      // only reads the prompt call would report "complete" for a dead run.
      if (process.env.HARNESS_FAIL === "prompt") throw new Error("no such session")
    },
    context: async (input) => {
      calls.push({ op: "context", input })
      // The LIVE 2.x shape: a message's parts ride `msg.content`, not `msg.parts`
      // (forge#30 — the 1.x shape here let the suite pass while live 2.x extracted
      // empty). A plugin reading only `msg.parts`/`msg.info.parts` must fail here.
      return [{ info: { role: "assistant" }, content: [{ type: "text", text: "PR https://x/pr/1 opened" }] }]
    },
    synthetic: async (input) => { calls.push({ op: "synthetic", input }) },
  },
}

const mod = await import(pathToFileURL(pluginPath).href)

let tools
if (host === "v1") {
  const hooks = await mod.default.server({ client: v1client, directory: workspace, worktree: workspace, project: {} })
  tools = hooks.tool ?? {}
} else {
  await mod.default.setup(v2ctx)
  tools = registered
}
if (!tools.dispatch) {
  console.log(JSON.stringify({ error: `no dispatch tool (${host})`, tools: Object.keys(tools) }))
  process.exit(0)
}

const v1ctx = { sessionID: "ses_parent", messageID: "m", agent: "build", directory: workspace, worktree: workspace }
// The 2.x tool ctx: the runtime hands the executing tool the calling session's id —
// the round trip's closing postback addresses the parent through it.
const v2toolctx = { sessionID: "ses_parent" }
// one call, or a SEQUENCE of calls in the same plugin instance (task_id memory)
const parsed = JSON.parse(argsJson)
const seq = Array.isArray(parsed) ? parsed : [parsed]
const run = ({ _tool, ...args }) => {
  const t = tools[_tool ?? "dispatch"]
  if (!t) return Promise.resolve({ error: `no tool '${_tool}'`, tools: Object.keys(tools) })
  if (host === "v1") return t.execute(args, v1ctx).catch((e) => ({ threw: String(e?.message ?? e) }))
  // Faithful to the 2.x runtime: a tool result carrying `output` while the tool
  // definition declares no output schema DIES (2.0.8 core/src/tool/runtime.ts:46,
  // verified live — forge#25): the call is destroyed, the caller never sees the
  // result. Model the die so the suite cannot pass a shape the live host kills.
  return t.execute(args, v2toolctx)
    .then((res) => (res !== null && typeof res === "object" && "output" in res
      ? { died: "Tool result declared output without an output schema" } : res))
    .catch((e) => ({ threw: String(e?.message ?? e) }))
}
const results = []
for (const args of seq) {
  if (args.parallel) results.push(...(await Promise.all(args.parallel.map(run))))
  else results.push(await run(args))
}
// The launcher is non-blocking: create + the worker prompt happen inline, but the worker
// wait + result read + <run-closed> postback run on a DETACHED waiter that outlives
// execute(). Let those settle (every mock resolves immediately) before snapshotting calls.
await new Promise((r) => setTimeout(r, 80))
console.log(JSON.stringify({ host, result: results[results.length - 1], results, calls }))
