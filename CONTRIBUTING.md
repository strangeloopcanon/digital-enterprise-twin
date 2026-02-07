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

If `bd` reports a daemon repo-id mismatch, run:

```bash
bd --no-daemon migrate --update-repo-id
bd --no-daemon sync --flush-only
bd daemon restart
```

Then continue normal `bd` usage (`bd ready`, `bd update`, `bd close`).
