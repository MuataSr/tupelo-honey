#!/bin/bash
# FCLE Tutor — Dual Qwen3.5-4B server launcher
# Router: port 8082 (ctx 4096) — intent classification
# Teacher: port 8083 (ctx 8192) — Socratic response generation
# Both use --reasoning off for clean content output

LLAMA_BIN="/home/muatasr/llama.cpp/build-vulkan/bin/llama-server"
MODEL="/home/muatasr/.local/share/models/qwen-family/qwen3.5-4b/Qwen3.5-4B-Q4_K_M.gguf"

# Kill any existing instances
for PORT in 8082 8083; do
    PID=$(lsof -ti:$PORT 2>/dev/null)
    if [ -n "$PID" ]; then
        echo "Killing existing server on port $PORT (PID $PID)"
        kill $PID 2>/dev/null
    fi
done
sleep 2

# Start router (low temp for consistent classification)
nohup $LLAMA_BIN \
    -m $MODEL \
    --port 8082 --host 127.0.0.1 \
    --ctx-size 4096 --parallel 1 --keep 1024 \
    -t 4 -ngl 99 -b 512 \
    --temp 0.1 \
    --reasoning off \
    > /tmp/router_4b.log 2>&1 &
ROUTER_PID=$!
echo "Router starting on port 8082 (PID $ROUTER_PID)"

# Start teacher (higher temp for varied Socratic responses)
nohup $LLAMA_BIN \
    -m $MODEL \
    --port 8083 --host 127.0.0.1 \
    --ctx-size 8192 --parallel 1 --keep 2048 \
    -t 4 -ngl 99 -b 512 \
    --temp 0.7 \
    --reasoning off \
    > /tmp/teacher_4b.log 2>&1 &
TEACHER_PID=$!
echo "Teacher starting on port 8083 (PID $TEACHER_PID)"

# Health checks
echo "Waiting for servers to load..."
for i in $(seq 1 30); do
    ROUTER_OK=$(curl -sf http://127.0.0.1:8082/health 2>/dev/null)
    TEACHER_OK=$(curl -sf http://127.0.0.1:8083/health 2>/dev/null)
    if [ -n "$ROUTER_OK" ] && [ -n "$TEACHER_OK" ]; then
        echo "Both servers ready!"
        echo "  Router:  PID $ROUTER_PID, port 8082"
        echo "  Teacher: PID $TEACHER_PID, port 8083"
        exit 0
    fi
    sleep 2
done

echo "WARNING: Servers did not respond within 60s"
echo "  Router:  $([ -n "$ROUTER_OK" ] && echo OK || echo FAILED)"
echo "  Teacher: $([ -n "$TEACHER_OK" ] && echo OK || echo FAILED)"
exit 1
