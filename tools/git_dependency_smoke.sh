#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${1:-$(pwd)}"
TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

python3.11 -m venv "${TMP_DIR}/venv"
source "${TMP_DIR}/venv/bin/activate"
python -m pip install --upgrade pip setuptools wheel >/dev/null

# Match external consumer behavior: install from a git URL (local file remote here).
python -m pip install "git+file://${REPO_ROOT}" >/dev/null

python - <<'PY'
from vei.sdk import create_session, get_scenario_manifest

manifest = get_scenario_manifest("multi_channel")
assert manifest.name == "multi_channel"

session = create_session(seed=42042, scenario_name="multi_channel")
obs = session.observe()
assert isinstance(obs.get("action_menu"), list)

page = session.call_tool("browser.read", {})
assert "url" in page

print("git dependency smoke passed")
PY
