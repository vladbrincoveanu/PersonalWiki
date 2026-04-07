#!/bin/bash
# VKE - Verified Knowledge Engine
# Usage: ./vke.sh <url> [vault_path]

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VAULT_PATH="${2:-$OBSIDIAN_VAULT_PATH}"
URL="$1"

if [ -z "$URL" ]; then
    echo "Usage: vke <url> [vault_path]"
    echo "Example: vke https://arxiv.org/pdf/2309.06180 ~/Documents/ObsidianVault/openclaw"
    exit 1
fi

if [ -z "$VAULT_PATH" ]; then
    VAULT_PATH="$HOME/Documents/ObsidianVault/openclaw"
fi

if [ -z "$ANTHROPIC_AUTH_TOKEN" ]; then
    echo "Error: ANTHROPIC_AUTH_TOKEN not set"
    echo "Run: export ANTHROPIC_AUTH_TOKEN=your_token"
    exit 1
fi

echo "VKE - Verifying: $URL"
echo "Vault: $VAULT_PATH"
echo ""

dotnet "$SCRIPT_DIR/src/Vke.Full/bin/Release/net10.0/Vke.Full.dll" \
    --url "$URL" \
    --vault "$VAULT_PATH" \
    --parallel 5
