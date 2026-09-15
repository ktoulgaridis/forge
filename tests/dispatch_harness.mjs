// Behavioural harness for the emitted opencode `dispatch` tool.
// Loads a RENDERED plugin file, hands it a fake opencode client, runs ONE dispatch
// against a REAL temp git workspace, and prints what happened as JSON.
//
// usage: node dispatch_harness.mjs <plugin.js> <workspace-dir> '<args-json>'
import { pathToFileURL } from "node:url"

const [, , pluginPath, workspace, argsJson] = process.argv
const calls = []
const client = {
  session: {
    create: async (input) => {
      calls.push({ op: "create", input })
      if (process.env.HARNESS_FAIL === "create") return { error: { name: "ProviderError", message: "boom" } }
      return { data: { id: `ses_${calls.filter((c) => c.op === "create").length}` } }
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

// The rendered plugin imports `@opencode-ai/plugin` (present at runtime inside opencode).
// Shim just what the tool helper offers: tool() and a chainable schema builder.
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

const mod = await import(pathToFileURL(pluginPath).href)
const factory = mod.default ?? Object.values(mod).find((v) => typeof v === "function")
const hooks = await factory({ client, directory: workspace, worktree: workspace, project: {} })
const tools = hooks.tool ?? {}
if (!tools.dispatch) {
  console.log(JSON.stringify({ error: "no dispatch tool", tools: Object.keys(tools) }))
  process.exit(0)
}
const ctx = { sessionID: "ses_parent", messageID: "m", agent: "build", directory: workspace, worktree: workspace }
// one call, or a SEQUENCE of calls in the same plugin instance (task_id memory).
// A call may name a different tool in the same plugin instance via `_tool`
// (e.g. {"_tool": "dispatch_read", "task_id": "ses_1"}); it defaults to `dispatch`.
const parsed = JSON.parse(argsJson)
const seq = Array.isArray(parsed) ? parsed : [parsed]
const run = ({ _tool, ...args }) => {
  const t = tools[_tool ?? "dispatch"]
  if (!t) return Promise.resolve({ error: `no tool '${_tool}'`, tools: Object.keys(tools) })
  return t.execute(args, ctx).catch((e) => ({ threw: String(e?.message ?? e) }))
}
const results = []
for (const args of seq) {
  if (args.parallel) results.push(...(await Promise.all(args.parallel.map(run))))
  else results.push(await run(args))
}
console.log(JSON.stringify({ result: results[results.length - 1], results, calls }))
