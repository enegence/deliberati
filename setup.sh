#!/bin/bash
# Deliberati — first-time setup

set -e

PROJECT_ROOT="$(dirname "$(realpath "$0")")"
ENV_FILE="$PROJECT_ROOT/.env"

echo ""
echo "  Deliberati — first-time setup"
echo "  ────────────────────────────────────────"
echo ""

# ── Check required tools ──────────────────────────────────────────────────────

missing=()
command -v uv  >/dev/null 2>&1 || missing+=("uv  (https://docs.astral.sh/uv/)")
command -v npm >/dev/null 2>&1 || missing+=("npm (https://nodejs.org/)")
if [ ${#missing[@]} -gt 0 ]; then
    echo "Missing required tools:"
    for tool in "${missing[@]}"; do
        echo "  - $tool"
    done
    echo ""
    echo "Install them and re-run setup.sh"
    exit 1
fi

# ── OpenRouter API key ────────────────────────────────────────────────────────

if [ -f "$ENV_FILE" ] && grep -q "OPENROUTER_API_KEY=" "$ENV_FILE" 2>/dev/null; then
    existing_key=$(grep -E '^OPENROUTER_API_KEY=' "$ENV_FILE" | tail -n 1 | cut -d '=' -f 2-)
    if [ -n "$existing_key" ]; then
        echo ".env already contains an OPENROUTER_API_KEY."
        read -r -p "  Overwrite it? [y/N] " overwrite
        if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
            echo "Keeping existing key."
            SKIP_KEY=true
        fi
    fi
fi

if [ -z "$SKIP_KEY" ]; then
    echo "Get your API key at https://openrouter.ai/"
    echo ""
    read -r -p "  OpenRouter API key (sk-or-v1-...): " api_key
    if [ -z "$api_key" ]; then
        echo "No key provided. Add OPENROUTER_API_KEY to .env manually before starting."
    else
        if [ -f "$ENV_FILE" ]; then
            # Remove any existing key line, append new one
            grep -v "^OPENROUTER_API_KEY=" "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
        fi
        echo "OPENROUTER_API_KEY=$api_key" >> "$ENV_FILE"
        echo "  Saved to .env"
    fi
fi

echo ""

# ── Database URL (optional) ───────────────────────────────────────────────────

echo "Postgres is optional for local dev — start.sh will auto-spin one up via Docker."
echo "Leave blank unless you have an existing Postgres instance to use."
echo ""
read -r -p "  DATABASE_URL (leave blank to skip): " db_url
if [ -n "$db_url" ]; then
    if [ -f "$ENV_FILE" ]; then
        grep -v "^DATABASE_URL=" "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
    fi
    echo "DATABASE_URL=$db_url" >> "$ENV_FILE"
    echo "  Saved to .env"
fi

echo ""

# ── Install dependencies ──────────────────────────────────────────────────────

read -r -p "Install Python and JS dependencies now? [Y/n] " install_deps
if [[ ! "$install_deps" =~ ^[Nn]$ ]]; then
    echo ""
    echo "Installing Python dependencies..."
    cd "$PROJECT_ROOT" && uv sync
    echo ""
    echo "Installing frontend dependencies..."
    cd "$PROJECT_ROOT/frontend" && npm install
    cd "$PROJECT_ROOT"
    echo ""
    echo "  Dependencies installed."
fi

echo ""
echo "  ────────────────────────────────────────"
echo "  Setup complete."
echo ""
echo "  Run the app:"
echo "    ./start.sh"
echo ""
echo "  On first launch, open the URL and create your admin account."
echo "  The app will prompt you automatically — no extra steps needed."
echo ""
