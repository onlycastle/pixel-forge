#!/usr/bin/env bash
# Start both backend (FastAPI) and frontend (Vite) for local development.
# Logs go to /tmp so the terminal stays clean.
# Usage: ./dev.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_LOG="/tmp/pixel-forge-backend.log"
FRONTEND_LOG="/tmp/pixel-forge-frontend.log"

cleanup() {
  echo ""
  echo "Shutting down..."
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null
  wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
  echo "Done."
}
trap cleanup EXIT

# Backend
source "$SCRIPT_DIR/.venv/bin/activate"
uvicorn web.server:app --reload --app-dir "$SCRIPT_DIR" > "$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

# Frontend
cd "$SCRIPT_DIR/web/frontend"
npm run dev > "$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

sleep 1

echo "================================================"
echo "  Pixel Forge Dev Server"
echo "================================================"
echo ""
echo "  Frontend: http://localhost:5173  <-- open this"
echo "  Backend:  http://localhost:8000"
echo ""
echo "  Logs:"
echo "    Backend:  tail -f $BACKEND_LOG"
echo "    Frontend: tail -f $FRONTEND_LOG"
echo ""
echo "  Press Ctrl+C to stop both."
echo "================================================"

wait
