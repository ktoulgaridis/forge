// Behavioural harness for the emitted opencode shell guard (plugin/shell-guard.js): load
// the RENDERED plugin with a fake host, fire each scenario's tool call through the host's
// before-tool hook, and print, per scenario, whether the guard let it run or threw (and
// why) — one JSON array, in scenario order.
//
// The emitted plugin carries BOTH host entrypoints:
//   host v1 — opencode 1.18.29+: `server({directory})` returns the 1.x hooks. The 1.x
//             before-tool input carries no agent, so the guard learns each session's agent
//             from `chat.params` (fired before every model request); each scenario runs in
//             its own session, and `chat.params` fires for it unless `known` is false.
//   host v2 — opencode 2.x: `setup(ctx)` registers `ctx.tool.hook("execute.before")`,
//             whose event carries the agent (`known: false` leaves it out).
//
// usage: node shell_guard_harness.mjs <plugin.js> <directory> '<scenarios-json>' [host]
//   scenarios: [{ agent, tool, command, known? }, ...]   (`command` may be any JSON value)
import { pathToFileURL } from "node:url"

const [, , pluginPath, directory, scenariosJson, hostArg] = process.argv
const host = hostArg === "v2" ? "v2" : "v1"
const scenarios = JSON.parse(scenariosJson)
const mod = await import(pathToFileURL(pluginPath).href)

let fire
if (host === "v1") {
  const hooks = await mod.default.server({ client: {}, directory, worktree: directory, project: {} })
  fire = async (s, i) => {
    const sessionID = `s${i}`
    if (s.known !== false) await hooks["chat.params"]?.({ sessionID, agent: s.agent, model: {}, provider: {}, message: {} }, { options: {} })
    return hooks["tool.execute.before"]({ tool: s.tool, sessionID, callID: `c${i}` }, { args: { command: s.command } })
  }
} else {
  const hooks = {}
  const ctx = {
    location: { directory },
    tool: { hook: async (name, cb) => { hooks[name] = cb; return { dispose: async () => {} } }, transform: async () => ({ dispose: async () => {} }) },
    session: { hook: async () => ({ dispose: async () => {} }) },
  }
  await mod.default.setup(ctx)
  fire = (s, i) => hooks["execute.before"]({
    tool: s.tool, sessionID: `s${i}`, ...(s.known !== false ? { agent: s.agent } : {}),
    messageID: `m${i}`, id: `c${i}`, input: { command: s.command },
  })
}

const out = []
for (const [i, s] of scenarios.entries()) {
  let threw = null
  try { await fire(s, i) } catch (e) { threw = String(e?.message ?? e) }
  out.push(threw)
}
console.log(JSON.stringify({ host, threw: out }))
