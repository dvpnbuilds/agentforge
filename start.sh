#!/usr/bin/env bash
set -euo pipefail
cd /root/agentforge
export HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
exec python3 server.py
