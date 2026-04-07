#!/bin/bash
# VKE Quick - No LLM needed
# Usage: ./vke-quick.sh <url> [vault_path]

VAULT_PATH="${2:-$OBSIDIAN_VAULT_PATH}"
URL="$1"

if [ -z "$URL" ]; then
    echo "Usage: vke-quick <url> [vault_path]"
    echo "Example: vke-quick https://arxiv.org/pdf/2309.06180 ~/Documents/ObsidianVault/openclaw"
    exit 1
fi

if [ -z "$VAULT_PATH" ]; then
    VAULT_PATH="$HOME/Documents/ObsidianVault/openclaw"
fi

echo "VKE Quick - Verifying: $URL"
echo "Vault: $VAULT_PATH"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

dotnet "$SCRIPT_DIR/src/Vke.Simple/bin/Release/net10.0/Vke.Simple.dll" \
    --url "$URL" \
    --vault "$VAULT_PATH"
