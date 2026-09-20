// Behavioural harness for the emitted opencode reminders plugin: feed it events and
// the compaction hook with a fake host, print what it did.
//
// The emitted plugin carries BOTH host entrypoints:
//   host v1 — opencode 1.18.29+: `server({client})` returns the 1.x hooks (the toast +
//             the compaction push). The 1.x SDK shim stays (server() imports nothing,
//             but keep parity with dispatch_harness).
//   host v2 — opencode 2.x: `setup(ctx)` registers `session.hook("compaction")`; the
//             scenario invokes the captured hook with a fake event and the pushed
//             system lines are reported.
//
// usage: node reminders_harness.mjs <plugin.js> '<scenario-json>' [host]
//   scenario: { "event": {...} } | { "compacting": true }
import { pathToFileURL } from "node:url"

const [, , pluginPath, scenarioJson, hostArg] = process.argv
const host = hostArg === "v2" ? "v2" : "v1"

const mod = await import(pathToFileURL(pluginPath).href)
const scenario = JSON.parse(scenarioJson)
const toasts = []
const context = []
const system = []

if (host === "v1") {
  const client = { tui: { showToast: async (input) => { toasts.push(input.body) } } }
  const hooks = await mod.default.server({ client, directory: "/tmp", worktree: "/tmp", project: {} })
  if (scenario.event) await hooks.event?.({ event: scenario.event })
  if (scenario.compacting) await hooks["experimental.session.compacting"]?.({ sessionID: "s" }, { context })
} else {
  const hooks = {}
  const ctx = { session: { hook: async (kind, fn) => { hooks[kind] = fn } } }
  await mod.default.setup(ctx)
  if (scenario.compacting) {
    const event = { system: [] }
    await hooks.compaction?.(event)
    for (const s of event.system) system.push(s.text)
  }
}

console.log(JSON.stringify({ host, toasts, context, system }))
