// Behavioural harness for the emitted opencode wiki-pull plugin: load it against a
// fake host, fire top-level session starts, print what the engineer was shown.
//
// The wiki path comes from the environment (the test sets the org's wiki env var).
//   host v1 — opencode 1.18.29+: `server({client})`; the harness fires two
//             `session.created` events (each awaits a pull) and reports every toast.
//   host v1-noclient — the 1.x entrypoint with no client: the toast throws, and the
//             un-awaited load/interval reports must swallow it (node exits non-zero on an
//             unhandled rejection).
//   host v2 — opencode 2.x: `setup(ctx)`; there is no server-side toast on 2.x, so
//             the harness only proves setup runs and returns a teardown.
//
// usage: node wiki_pull_harness.mjs <plugin.js> [host]
import { pathToFileURL } from "node:url"

const [, , pluginPath, hostArg] = process.argv
const host = ["v2", "v1-noclient"].includes(hostArg) ? hostArg : "v1"
const mod = await import(pathToFileURL(pluginPath).href)
const toasts = []

if (host === "v1") {
  const client = { tui: { showToast: async (input) => { toasts.push(input.body) } } }
  const hooks = await mod.default.server({ client, directory: "/tmp", worktree: "/tmp", project: {} })
  const start = { type: "session.created", properties: { info: { id: "s1" } } }
  await hooks.event?.({ event: start })
  await hooks.event?.({ event: start })
} else if (host === "v1-noclient") {
  const hooks = await mod.default.server({})
  await hooks.event?.({ event: { type: "session.created", properties: { info: { id: "s1" } } } })
  await new Promise((r) => setTimeout(r, 200))  // let the un-awaited load report settle
} else {
  const teardown = await mod.default.setup({})
  if (typeof teardown === "function") teardown()
}

console.log(JSON.stringify({ host, toasts }))
