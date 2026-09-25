// --- the before-tool hook, on both hosts (rendered from ONE source into every blocking
// guard plugin; each emitted plugin stays one self-contained file, so a guard never
// depends on a sibling module the installer might have left out) ---------------------
//
//   - opencode 2.x loads `setup(ctx)`: `ctx.tool.hook("execute.before")`, whose event names
//     the calling agent. The shell tool is `shell`.
//   - opencode 1.18.29+ loads `server()`: `tool.execute.before`. Its input carries no
//     agent, so the plugin learns each session's agent from `chat.params`, which fires
//     before every model request (and so before any tool call it makes). A session whose
//     agent it never saw reaches the guard with `agent === undefined`. The shell tool is
//     `bash`.
// `guard(agent, tool, args, directory)` throws to reject the call; the model sees the
// reason as the tool's error.
const SHELL_TOOLS = ["bash", "shell"]

function beforeToolPlugin(id, guard) {
  return {
    id,

    /** opencode 2.x: the before-tool hook carries the agent. */
    async setup(ctx) {
      const directory = ctx.location.directory
      await ctx.tool.hook("execute.before", (event) => guard(event.agent, event.tool, event.input, directory))
      return () => {}
    },

    /** opencode 1.18.29+: learn each session's agent, then guard its tool calls. */
    async server({ directory }) {
      const agents = new Map()
      return {
        "chat.params": async (input) => { if (input?.sessionID) agents.set(input.sessionID, input.agent) },
        "tool.execute.before": async (input, output) =>
          guard(agents.get(input.sessionID), input.tool, output?.args, directory),
      }
    },
  }
}
