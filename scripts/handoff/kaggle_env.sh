# shellcheck shell=bash
# Source this file before any Kaggle call:  . scripts/handoff/kaggle_env.sh
#
# Why: Kaggle API tokens start with KGAT_. The Kaggle CLI (2.2.x) refuses a KGAT_ token
# that sits in KAGGLE_KEY or in the "key" field of ~/.kaggle/kaggle.json ("cannot be used
# as a legacy API key"). It accepts one only from KAGGLE_API_TOKEN or ~/.kaggle/access_token.
# This file moves a KGAT_ token to KAGGLE_API_TOKEN and unsets KAGGLE_KEY.
# It never prints the token.

_kaggle_json="${KAGGLE_CONFIG_DIR:-$HOME/.kaggle}/kaggle.json"
_kaggle_access="${KAGGLE_CONFIG_DIR:-$HOME/.kaggle}/access_token"

if [ -z "${KAGGLE_API_TOKEN:-}" ] && [ "${KAGGLE_KEY:-}" != "${KAGGLE_KEY#KGAT_}" ]; then
  export KAGGLE_API_TOKEN="$KAGGLE_KEY"
fi
if [ -z "${KAGGLE_API_TOKEN:-}" ] && [ ! -s "$_kaggle_access" ] && [ -f "$_kaggle_json" ]; then
  _tok="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("key",""))' "$_kaggle_json" 2>/dev/null)"
  case "$_tok" in
    KGAT_*) export KAGGLE_API_TOKEN="$_tok" ;;
  esac
  unset _tok
fi
if [ -n "${KAGGLE_API_TOKEN:-}" ] || [ -s "$_kaggle_access" ]; then
  unset KAGGLE_KEY
fi
unset _kaggle_json _kaggle_access

# Kaggle CLI to use. Default: the version pinned in pyproject (kaggle==2.2.4) via uv.
# Override with KAGGLE_BIN=/path/to/kaggle.
KAGGLE_BIN="${KAGGLE_BIN:-uv run kaggle}"
export KAGGLE_BIN
