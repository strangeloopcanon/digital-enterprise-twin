# Contributing

## Local setup

```bash
make setup
make all
```

## Before opening a PR

```bash
make check
make test
make llm-live      # requires OPENAI_API_KEY, or set VEI_LLM_LIVE_BYPASS=1
make deps-audit
```

## `bd` issue tracking after repo rename/fork

`bd` state lives in the local `.beads/` directory and should stay uncommitted.

If `bd` reports repo-id drift after a rename or fork, use the current `bd` export/import workflow described by `bd help`; older `bd sync` and daemon commands are no longer valid in newer `bd` releases.
