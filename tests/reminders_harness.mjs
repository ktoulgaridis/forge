// Behavioural harness for the emitted opencode reminders plugin: feed it events and
// the compaction hook with a fake client, print what it did.
// usage: node reminders_harness.mjs <plugin.js> '<scenario-json>'
//   scenario: { "event": {...} } | { "compacting": true }
import { pathToFileURL } from "node:url"
import { mkdirSync, writeFileSync } from "node:fs"
import { dirname, join } from "node:path"

const [, , pluginPath, scenarioJson] = process.argv
const shimDir = join(dirname(pluginPath), "node_modules", "@opencode-ai", "plugin")
mkdirSync(shimDir, { recursive: true })
writeFileSync(join(shimDir, "package.json"), JSON.stringify({ name: "@opencode-ai/plugin", type: "module", main: "index.js" }))
writeFileSync(join(shimDir, "index.js"), "export const tool = (i) => i; tool.schema = {}")

const toasts = []
const client = { tui: { showToast: async (input) => { toasts.push(input.body) } } }
const mod = await import(pathToFileURL(pluginPath).href)
const factory = mod.default ?? Object.values(mod).find((v) => typeof v === "function")
const hooks = await factory({ client, directory: "/tmp", worktree: "/tmp", project: {} })
const scenario = JSON.parse(scenarioJson)
const context = []
if (scenario.event) await hooks.event?.({ event: scenario.event })
if (scenario.compacting) await hooks["experimental.session.compacting"]?.({ sessionID: "s" }, { context })
console.log(JSON.stringify({ toasts, context, hooks: Object.keys(hooks) }))
