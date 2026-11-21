#!/usr/bin/env bash
# heretic (p-e-w/heretic, AGPL-3.0) - a separate local tool. NEXUS does not
# import or call it; it only writes a modified model that you may load into
# Ollama yourself. See README.md next to this file.
#
#   tools/heretic/run.sh MODEL [CONFIG] [heretic options...]
#   tools/heretic/run.sh Qwen/Qwen3-4B-Instruct-2507
#   tools/heretic/run.sh Qwen/Qwen3-4B-Instruct-2507 nosyco --quantization BNB_4BIT
#
# CONFIG: nosyco (less flattery, default), noslop (less filler), terse (shorter).
# Upstream's default config (refusal removal) is deliberately not offered:
# NEXUS works on real people and the model's refusals are one of its guards.
set -euo pipefail

VERSION=2.1.0
COMMIT=4f89482c0d63f2552a582215939910f9f45a3e5f   # tag v2.1.0; a commit cannot be moved
HERE=$(cd "$(dirname "$0")" && pwd)
VENV=$HERE/.venv

MODEL=${1:?usage: run.sh MODEL [CONFIG] [heretic options...]   (MODEL = Hugging Face id, e.g. Qwen/Qwen3-4B-Instruct-2507)}
CONFIG=${2:-nosyco}
case "$CONFIG" in
  nosyco) SHA=98b6097c005185583446a45a74c6d946e545c3fd24960efcdd744f9d8815a4ad ;;
  noslop) SHA=f58b61c2d7a09c0edd50f4b801411c732e8e9d48726573d22b57bbd2f29fd1a1 ;;
  terse)  SHA=c740a6834ff97f64a89c4eccd4c54448b6161d14f6b747c62b6b418888419f4c ;;
  *) echo "unsupported CONFIG: $CONFIG (nosyco | noslop | terse; refusal removal is not offered)" >&2; exit 2 ;;
esac
if [[ ! $MODEL =~ ^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$ || $MODEL == *..* ]]; then
  echo "bad MODEL: $MODEL (expected a Hugging Face id like Org/Name)" >&2; exit 2
fi
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/" >&2; exit 2; }
command -v nvidia-smi >/dev/null || echo "warning: no NVIDIA GPU found - this will be very slow" >&2

# own virtualenv, every package pinned by hash (requirements.lock); reused only
# when it was fully installed for this exact version
if [[ $(cat "$VENV/.heretic-version" 2>/dev/null) != "$VERSION" ]]; then
  rm -rf "$VENV"
  uv venv -q --python 3.12 "$VENV"
  uv pip sync -q --python "$VENV/bin/python" --require-hashes "$HERE/requirements.lock"
  echo "$VERSION" > "$VENV/.heretic-version"
fi

WORK="$HERE/work/${MODEL//\//__}-$CONFIG"
mkdir -p "$WORK"
TMP=$(mktemp "$WORK/.config.XXXXXX")
trap 'rm -f "$TMP"' EXIT
URL="https://raw.githubusercontent.com/p-e-w/heretic/$COMMIT/config.$CONFIG.toml"
status=0
curl -fsSL --proto '=https' --max-time 30 "$URL" -o "$TMP" || status=$?
if [[ $status != 0 ]]; then
  if [[ $status == 22 ]]; then echo "config not found upstream: $URL" >&2
  else echo "network error (curl $status) fetching $URL" >&2; fi
  exit 1
fi
echo "$SHA  $TMP" | sha256sum -c --quiet - || { echo "config checksum mismatch - refusing to run" >&2; exit 1; }
mv "$TMP" "$WORK/config.toml"

echo "config: $CONFIG  ->  $WORK"
echo "save the model under $WORK (not git-tracked); do not upload it to Hugging Face"
cd "$WORK"
exec "$VENV/bin/heretic" --model "$MODEL" "${@:3}"
