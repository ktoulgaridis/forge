// Behavioural harness for the emitted opencode verify guard (plugin/verify.js): load the
// RENDERED plugin with a fake host, fire ONE shell call through the host's before-tool
// hook, and print whether the guard let it run or threw (and why) as JSON.
//
// The emitted plugin carries BOTH host entrypoints:
//   host v1 — opencode 1.18.29+: `server({directory})` returns the 1.x hooks. The 1.x
//             before-tool input carries no agent, so the guard learns each session's agent
//             from `chat.params` (fired before every model request); the scenario fires it
//             unless `known` is false.
//   host v2 — opencode 2.x: `setup(ctx)` registers `ctx.tool.hook("execute.before")`,
//             whose event carries the agent.
//
// usage: node verify_harness.mjs <plugin.js> <directory> '<scenario-json>' [host]
//   scenario: { agent, tool, command, workdir?, known? }
import { pathToFileURL } from "node:url"

const [, , pluginPath, directory, scenarioJson, hostArg] = process.argv
const host = hostArg === "v2" ? "v2" : "v1"
const s = JSON.parse(scenarioJson)
const args = { command: s.command, ...(s.workdir ? { workdir: s.workdir } : {}) }
const mod = await import(pathToFileURL(pluginPath).href)

let fire
if (host === "v1") {
  const hooks = await mod.default.server({ client: {}, directory, worktree: directory, project: {} })
  if (s.known !== false) await hooks["chat.params"]?.({ sessionID: "s1", agent: s.agent, model: {}, provider: {}, message: {} }, { options: {} })
  fire = () => hooks["tool.execute.before"]({ tool: s.tool, sessionID: "s1", callID: "c1" }, { args })
} else {
  const hooks = {}
  const ctx = {
    location: { directory },
    tool: { hook: async (name, cb) => { hooks[name] = cb; return { dispose: async () => {} } }, transform: async () => ({ dispose: async () => {} }) },
    session: { hook: async () => ({ dispose: async () => {} }) },
  }
  await mod.default.setup(ctx)
  fire = () => hooks["execute.before"]({ tool: s.tool, sessionID: "s1", agent: s.agent, messageID: "m1", id: "c1", input: args })
}

let threw = null
try { await fire() } catch (e) { threw = String(e?.message ?? e) }
console.log(JSON.stringify({ host, threw }))
