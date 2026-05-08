#!/usr/bin/env bash
# Exposes the edge port via a public URL so Twilio webhooks can reach it.
# Tries cloudflared first, falls back to ngrok.
set -euo pipefail

EDGE_PORT="${EDGE_PORT:-8080}"

if command -v cloudflared >/dev/null 2>&1; then
  echo "Starting cloudflared tunnel to localhost:${EDGE_PORT}"
  echo "Set the printed https://*.trycloudflare.com URL as your Twilio number's voice webhook."
  exec cloudflared tunnel --url "http://localhost:${EDGE_PORT}"
fi

if command -v ngrok >/dev/null 2>&1; then
  echo "Starting ngrok on ${EDGE_PORT}"
  echo "Set the printed https://*.ngrok.app URL as your Twilio number's voice webhook."
  exec ngrok http "${EDGE_PORT}"
fi

echo "Neither cloudflared nor ngrok found on PATH."
echo "Install cloudflared (preferred) or ngrok and rerun: make tunnel"
exit 1
