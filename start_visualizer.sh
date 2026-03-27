#!/bin/bash
# ==========================================
# ETME Visualizer — Export + Serve
# ==========================================

PORT=3000

# 1. Activate environment
source .venv/bin/activate

# 2. Kill anything already on the port
PID=$(lsof -ti :$PORT 2>/dev/null)
if [ -n "$PID" ]; then
    echo "⚡ Clearing port $PORT (PID $PID)..."
    kill -9 $PID 2>/dev/null
    sleep 0.5
fi

# 3. Export the ETME analysis
echo ""
echo "🔬 Running ETME Phase 1 + Phase 2 analysis..."
echo "-----------------------------------------------"
python export_etme_data.py
if [ $? -ne 0 ]; then
    echo "❌ Export failed. Check your MIDI files and Python environment."
    exit 1
fi

# 4. Serve the visualizer
echo ""
echo "-----------------------------------------------"
echo "🎹 Visualizer live at: http://localhost:$PORT/visualizer.html"
echo "   Press Ctrl+C to stop."
echo "-----------------------------------------------"
python -m http.server $PORT
