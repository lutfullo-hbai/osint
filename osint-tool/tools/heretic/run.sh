#!/usr/bin/env bash
# heretic (p-e-w/heretic, AGPL-3.0) - a separate, offline tool. NEXUS does not
# import or call it; it only writes a modified model that you may load into
# Ollama yourself. See README.md next to this file.
#
#   tools/heretic/run.sh MODEL [CONFIG]
#   tools/heretic/run.sh Qwen/Qwen3-4B-Instruct-2507            # nosyco (default)
#   tools/heretic/run.sh Qwen/Qwen3-4B-Instruct-2507 terse
#
# CONFIG is one of upstream's config.<name>.toml files: nosyco (less flattery,
# the default here), noslop, terse, nohumor, emotions, default (removes refusals).
set -euo pipefail

VERSION=2.1.0                          # pinned: the package and its configs
HERE=$(cd "$(dirname "$0")" && pwd)
MODEL=${1:?usage: run.sh MODEL [CONFIG]   (MODEL = Hugging Face id, e.g. Qwen/Qwen3-4B-Instruct-2507)}
CONFIG=${2:-nosyco}
[[ $CONFIG =~ ^[a-z]+$ ]] || { echo "bad CONFIG: $CONFIG" >&2; exit 2; }
[[ $MODEL =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || { echo "bad MODEL: $MODEL" >&2; exit 2; }
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/" >&2; exit 2; }
command -v nvidia-smi >/dev/null || echo "warning: no NVIDIA GPU found - this will be very slow" >&2

# own virtualenv, outside the NEXUS images; Python 3.12 has torch wheels everywhere
if [[ ! -x $HERE/.venv/bin/heretic ]]; then
  uv venv --python 3.12 "$HERE/.venv"
  uv pip install --python "$HERE/.venv/bin/python" "heretic-llm==$VERSION"
fi

WORK="$HERE/work/$(echo "$MODEL" | tr / _)-$CONFIG"
mkdir -p "$WORK"
curl -fsSL "https://raw.githubusercontent.com/p-e-w/heretic/v$VERSION/config.$CONFIG.toml" -o "$WORK/config.toml" \
  || { echo "no such config: $CONFIG" >&2; exit 2; }
echo "config: $CONFIG  ->  $WORK (heretic asks at the end where to save the model)"
cd "$WORK"
exec "$HERE/.venv/bin/heretic" "$MODEL"
