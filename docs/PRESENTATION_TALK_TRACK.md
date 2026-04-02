# VEI Presentation Talk Track

So what: this is the shortest clean way to present VEI as a world studio for enterprises.

The goal is not to explain every subsystem. The goal is to make one idea obvious:

- VEI is one enterprise world kernel
- different companies can run on top of it
- different situations can be layered onto the same company
- different objectives can be layered onto the same situation
- the same runtime outputs later become training, eval, and agent-operations artifacts

## Fast Setup

Build the canonical story workspace:

```bash
vei showcase story \
  --root _vei_out/vertical_showcase \
  --run-id story_presentation \
  --vertical real_estate_management
```

Serve Studio:

```bash
vei ui serve \
  --root _vei_out/vertical_showcase/story_presentation/real_estate_management \
  --host 127.0.0.1 \
  --port 3011
```

Open:

- [http://127.0.0.1:3011](http://127.0.0.1:3011)

If you want the generated guide beside the UI, look for `presentation_guide.md` in the story workspace root:

- `_vei_out/vertical_showcase/story_presentation/real_estate_management/presentation_guide.md`

## Opening

Use this almost verbatim:

> VEI is a world studio for enterprises. The important thing here is not one workflow demo. The important thing is that we have one reusable kernel that can instantiate different companies, layer different situations onto them, change what success means, run agents inside those worlds, and then give us replayable artifacts from the exact same runtime.

## The Flow

Walk the UI in this order:

1. `Presentation`
2. `Company`
3. `Situation`
4. `Objective`
5. `Run`
6. `Branch + Outcome`
7. `Exports`

Do not jump around. The power comes from the sequence.

## What To Say

### 1. Presentation

Say:

> Start with the kernel. This is one enterprise runtime, one event spine, one contract engine, one branch-and-replay system.

Emphasize:

- this is not a static benchmark
- this is not a single industry demo
- this is not a one-off workflow wrapper

### 2. Company

Say:

> Now we instantiate a company world on top of that kernel. In this case it is Harbor Point Management, a real-estate management company with leases, vendors, unit readiness, work orders, tickets, documents, and communications.

Emphasize:

- the company is a stable world
- this is the base environment
- this same pattern also works for the marketing and storage companies

### 3. Situation

Say:

> The company stays the same. What changes now is the situation. We introduce a high-stakes opening conflict: lease drift, vendor coordination pressure, and operational deadlines.

Emphasize:

- the problem is an overlay, not a new world
- this is what makes the system flexible
- the same company can produce many futures

### 4. Objective

Say:

> Now we change what good means. The objective tells VEI how to judge success. That is separate from both the company and the situation.

Emphasize:

- one world, many objective functions
- this is the bridge to policy testing, reward shaping, and eval

### 5. Run

Say:

> Here we run the baseline and the comparison path through the same runtime. Every action lands in the same event spine with state changes, graph actions, tool resolution, and snapshots.

Emphasize:

- same runtime for workflow and agent behavior
- everything is inspectable
- this is already an observability surface

### 6. Branch + Outcome

Say:

> This is the key moment. Same company. Same underlying world. Different choices. Different business result.

Emphasize:

- this is why it feels like an engine
- branches are alternate futures, not handcrafted separate demos
- this is what later makes simulation, recovery testing, and decision analysis powerful

### 7. Exports

Say:

> The reason this matters strategically is that the same run can later become three different product layers: RL artifacts, continuous eval artifacts, and agent operations artifacts.

Emphasize:

- RL: state transitions, actions, outcomes
- eval: baseline versus comparison under the same setup
- agent ops: replay, tools, provenance, branching, contract findings

## Closing

Use this almost verbatim:

> The thesis is that enterprises need an Unreal Engine equivalent: a kernel that can represent the company, generate situations, run agents, and make outcomes legible. These three demos are not the product by themselves. They are proof that the kernel is flexible enough to become the platform underneath simulation, eval, training, and agent management.

## Best Meeting Shape

Recommended timing:

1. 60 seconds on the kernel thesis
2. 60 seconds on the company world
3. 60 seconds on situation plus objective
4. 90 seconds on run plus branch
5. 60 seconds on exports and platform story

Total:

- about 5 minutes for the core demo

## If They Ask Hard Questions

### “Is this just a benchmark harness?”

Answer:

> No. Benchmarks are one use case on top. The underlying thing is a stateful enterprise world with scenario overlays, objective overlays, branching, replay, and inspectable runtime traces.

### “Why is this defensible?”

Answer:

> Because the hard part is not drawing a UI or wiring a model to tools. The hard part is building a coherent world kernel, the contract system, the event spine, and the compiler that turns enterprise structure into runnable environments.

### “Why not just use production systems?”

Answer:

> Production systems are where risk is realized. This is where situations can be generated, branched, evaluated, and replayed safely before or alongside production.

### “Why does this become RL later?”

Answer:

> Because the primitives are already there: state, actions, outcomes, branchable trajectories, and deterministic replay.

### “Why does this become agent operations later?”

Answer:

> Because the runtime already records what the agent saw, what it did, which tools resolved, how the state changed, and why the outcome passed or failed.
