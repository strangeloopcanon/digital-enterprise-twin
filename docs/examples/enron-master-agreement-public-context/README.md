# Enron Master Agreement Example

This folder is a repo-owned saved Enron what-if example. It lets a fresh clone open a real historical branch point, inspect the dated public-company context that was already known by that branch date, and read the saved compare-path results without depending on ignored local output folders.

## Open It In Studio

```bash
vei ui serve \
  --root docs/examples/enron-master-agreement-public-context/workspace \
  --host 127.0.0.1 \
  --port 3055
```

Open `http://127.0.0.1:3055`.

## What This Example Covers

- Historical branch point: Debra Perlingiere sending the `Master Agreement` draft to Cargill on September 27, 2000
- Saved branch scene: 6 prior messages and 84 recorded future events
- Public-company slice at that date: 2 financial checkpoints and 0 public-news events
- Bounded LLM path: keep the draft inside Enron, ask Gerald Nemec for legal review, and hold the outside send
- JEPA forecast: same 84-event horizon, risk from `1.000` to `0.983`, outside-send delta `-29`

## Files

- `workspace/`: saved workspace you can open in Studio
- `whatif_experiment_overview.md`: short human-readable run summary
- `whatif_experiment_result.json`: saved combined result for the example bundle
- `whatif_llm_result.json`: bounded message-path result
- `whatif_ejepa_result.json`: JEPA forecast result

## Constraint

This saved example is meant for inspection. The original full Enron Rosetta archive is not included in the repo, so whole-history Enron search and full-corpus reruns still require a local Rosetta checkout.
