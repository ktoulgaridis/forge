// Behavioural harness for the emitted opencode wiki-pull plugin: load it against a
// fake host, fire top-level session starts, print what the engineer was shown.
//
// The wiki path comes from the environment (the test sets the org's wiki env var).
//   host v1 — opencode 1.18.29+: `server({client})`; the harness fires two
//             `session.created` events (each awaits a pull) and reports every toast.
//   host v2 — opencode 2.x: `setup(ctx)`; there is no server-side toast on 2.x, so
//             the harness only proves setup runs and returns a teardown.
//
// usage: node wiki_pull_harness.mjs <plugin.js> [host]
import { pathToFileURL } from "node:url"

const [, , pluginPath, hostArg] = process.argv
const host = hostArg === "v2" ? "v2" : "v1"
const mod = await import(pathToFileURL(pluginPath).href)
const toasts = []

if (host === "v1") {
  const client = { tui: { showToast: async (input) => { toasts.push(input.body) } } }
  const hooks = await mod.default.server({ client, directory: "/tmp", worktree: "/tmp", project: {} })
  const start = { type: "session.created", properties: { info: { id: "s1" } } }
  await hooks.event?.({ event: start })
  await hooks.event?.({ event: start })
} else {
  const teardown = await mod.default.setup({})
  if (typeof teardown === "function") teardown()
}

console.log(JSON.stringify({ host, toasts }))
