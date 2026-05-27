#!/bin/bash
# LLM Council - Robust Dynamic Port Starter (Clean Version)

echo "🚀 Starting LLM Council with dynamic ports..."

# ==================== Find Available Ports ====================
find_available_port() {
    local base_port=$1
    local port=$base_port
    local max_attempts=100

    while [ $max_attempts -gt 0 ]; do
        if ! ss -tuln 2>/dev/null | grep -q ":$port " 2>/dev/null && \
           ! (echo > /dev/tcp/127.0.0.1/$port) >/dev/null 2>&1; then
            echo "$port"
            return 0
        fi
        ((port++))
        ((max_attempts--))
    done

    echo "❌ Could not find an available port starting from $base_port" >&2
    exit 1
}

BACKEND_PORT=$(find_available_port 8001)
FRONTEND_PORT=$(find_available_port 5176)

echo "✅ Backend  will use port: $BACKEND_PORT"
echo "✅ Frontend will use port: $FRONTEND_PORT"
echo ""

PROJECT_ROOT="$(dirname "$(realpath "$0")")"

read_dotenv_value() {
    local key=$1
    local value

    if [ ! -f "$PROJECT_ROOT/.env" ]; then
        return 1
    fi

    value=$(grep -E "^${key}=" "$PROJECT_ROOT/.env" 2>/dev/null | tail -n 1 | cut -d '=' -f 2-)
    value="${value%\"}"
    value="${value#\"}"
    value="${value%\'}"
    value="${value#\'}"

    if [ -n "$value" ]; then
        echo "$value"
        return 0
    fi

    return 1
}

if [ -z "${DATABASE_URL:-}" ]; then
    ENV_DATABASE_URL=$(read_dotenv_value "DATABASE_URL" || true)
    if [ -n "$ENV_DATABASE_URL" ]; then
        export DATABASE_URL="$ENV_DATABASE_URL"
    fi
fi

if [ -z "${DATABASE_URL:-}" ]; then
    ENV_DATABASE_URL_FILE="${DATABASE_URL_FILE:-}"
    if [ -z "$ENV_DATABASE_URL_FILE" ]; then
        ENV_DATABASE_URL_FILE=$(read_dotenv_value "DATABASE_URL_FILE" || true)
    fi
    if [ -n "$ENV_DATABASE_URL_FILE" ] && [ -f "$ENV_DATABASE_URL_FILE" ]; then
        export DATABASE_URL="$(tr -d '\r\n' < "$ENV_DATABASE_URL_FILE")"
    fi
fi

# ==================== Ensure Local Postgres ====================
POSTGRES_CONTAINER_NAME="${COUNCIL_POSTGRES_CONTAINER:-llm-council-postgres-dev}"
POSTGRES_VOLUME="${COUNCIL_POSTGRES_VOLUME:-llm-council_postgres_data}"
POSTGRES_USER="${COUNCIL_POSTGRES_USER:-llm_council}"
POSTGRES_PASSWORD="${COUNCIL_POSTGRES_PASSWORD:-llm_council}"
POSTGRES_DB="${COUNCIL_POSTGRES_DB:-llm_council}"

get_postgres_host_port() {
    local mapping
    mapping=$(docker port "$POSTGRES_CONTAINER_NAME" 5432/tcp 2>/dev/null | head -n 1 || true)
    mapping="${mapping##*:}"

    if [[ "$mapping" =~ ^[0-9]+$ ]]; then
        echo "$mapping"
        return 0
    fi

    return 1
}

ensure_postgres() {
    if [ -n "${DATABASE_URL:-}" ]; then
        echo "✅ Using DATABASE_URL from environment/.env"
        return 0
    fi

    if ! command -v docker >/dev/null 2>&1; then
        echo "❌ DATABASE_URL is not set and Docker is not available to start local Postgres"
        echo "   Set DATABASE_URL in .env, then restart the app."
        exit 1
    fi

    local postgres_port

    if docker ps --format '{{.Names}}' | grep -Fxq "$POSTGRES_CONTAINER_NAME"; then
        postgres_port=$(get_postgres_host_port) || {
            echo "❌ Existing $POSTGRES_CONTAINER_NAME container does not publish port 5432"
            echo "   Set DATABASE_URL manually or recreate the dev Postgres container."
            exit 1
        }
    elif docker ps -a --format '{{.Names}}' | grep -Fxq "$POSTGRES_CONTAINER_NAME"; then
        echo "Starting existing Postgres container $POSTGRES_CONTAINER_NAME ..."
        docker start "$POSTGRES_CONTAINER_NAME" >/dev/null || exit 1
        postgres_port=$(get_postgres_host_port) || {
            echo "❌ Existing $POSTGRES_CONTAINER_NAME container does not publish port 5432"
            echo "   Set DATABASE_URL manually or recreate the dev Postgres container."
            exit 1
        }
    else
        postgres_port=$(find_available_port 5435)
        echo "Creating Postgres container $POSTGRES_CONTAINER_NAME on 127.0.0.1:$postgres_port ..."
        docker run -d \
            --name "$POSTGRES_CONTAINER_NAME" \
            -e POSTGRES_USER="$POSTGRES_USER" \
            -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
            -e POSTGRES_DB="$POSTGRES_DB" \
            -v "$POSTGRES_VOLUME:/var/lib/postgresql/data" \
            -v "$PROJECT_ROOT/db/postgres:/docker-entrypoint-initdb.d:ro" \
            -p "127.0.0.1:$postgres_port:5432" \
            pgvector/pgvector:pg17 >/dev/null || exit 1
    fi

    echo "Waiting for Postgres to become ready..."
    for i in {1..40}; do
        if docker exec "$POSTGRES_CONTAINER_NAME" pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB" >/dev/null 2>&1; then
            export DATABASE_URL="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@127.0.0.1:$postgres_port/$POSTGRES_DB"
            echo "✅ Postgres is ready on 127.0.0.1:$postgres_port"
            return 0
        fi
        sleep 0.5
    done

    echo "❌ Postgres did not become ready in time"
    exit 1
}

ensure_postgres

# ==================== Start Backend ====================
echo "Starting Backend on http://localhost:$BACKEND_PORT ..."
cd "$PROJECT_ROOT" || exit 1

ALLOWED_ORIGINS="http://localhost:$FRONTEND_PORT" \
uv run python -m uvicorn backend.main:app \
    --host 127.0.0.1 \
    --port "$BACKEND_PORT" \
    --reload &
BACKEND_PID=$!

# ==================== Start Worker ====================
echo "Starting Worker ..."
cd "$PROJECT_ROOT" || exit 1
uv run python -m backend.worker &
WORKER_PID=$!

# ==================== Start Frontend ====================
echo "Starting Frontend on http://localhost:$FRONTEND_PORT ..."
cd "$PROJECT_ROOT/frontend" || { echo "❌ Error: frontend directory not found"; kill $BACKEND_PID 2>/dev/null; exit 1; }

VITE_API_BASE_URL="http://localhost:$BACKEND_PORT" \
npm run dev -- \
    --port "$FRONTEND_PORT" &
FRONTEND_PID=$!

# ==================== Wait for Servers ====================
echo "Waiting for servers to become ready..."

# Wait for backend
for i in {1..25}; do
    if curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
        echo "✅ Backend is ready on http://localhost:$BACKEND_PORT"
        break
    fi
    sleep 0.5
done

if ! curl -fsS "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    echo "❌ Backend did not become healthy on http://localhost:$BACKEND_PORT"
    kill $BACKEND_PID $WORKER_PID 2>/dev/null
    wait 2>/dev/null
    exit 1
fi

# Wait for frontend
for i in {1..20}; do
    if ss -tuln 2>/dev/null | grep -q ":$FRONTEND_PORT "; then
        echo "✅ Frontend is ready on http://localhost:$FRONTEND_PORT"
        break
    fi
    sleep 0.5
done

echo ""
echo "🎉 LLM Council is running!"
echo "   Backend:   http://localhost:$BACKEND_PORT"
echo "   Worker:    background process active"
echo "   Frontend:  http://localhost:$FRONTEND_PORT"
echo ""
echo "Press Ctrl+C to stop both servers"

# ==================== Cleanup on Ctrl+C ====================
trap '
    echo -e "\n\n🛑 Stopping servers..."
    kill $BACKEND_PID $WORKER_PID $FRONTEND_PID 2>/dev/null
    wait 2>/dev/null
    echo "✅ Servers stopped."
    exit 0
' SIGINT SIGTERM

wait
