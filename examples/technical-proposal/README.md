# technical-proposal - abstract RFC cook

Use this shape when you want several agents to propose a buildable path
for an underspecified product or architecture problem.

Good fits:

- "How should we add offline mode to this product?"
- "What is the best control-plane architecture for these agents?"
- "Should this subsystem be event-sourced, state-machine based, or a
  simpler CRUD service?"

The brief forces each participant to choose one direction, compare
alternatives, and expose risk. The judge brief scores realism and
tradeoffs instead of rewarding long generic architecture prose.

## Adapt

Replace the files in `raw/` with your real context. Keep the output as a
single `PROPOSAL.md` unless you have a reason to ask for diagrams or
config examples as named extra artifacts.

Typical timeouts:

- 20-30 minutes for a lightweight brainstorm over small inputs.
- 60-90 minutes for a deep proposal over a real repo snapshot.
