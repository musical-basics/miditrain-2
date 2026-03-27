# ETME Visualizer (miditrain-2)

4D Electro-Thermodynamic Music Engine — Harmonic regime detection and visualization for MIDI performances.

## Architecture

```
export_etme_data.py    → Python pipeline: MIDI → harmonic analysis → JSON
STS_bootstrapper.py    → Harmonic Regime Detector + Single Time Signature Bootstrapper
particle.py            → MIDI particle data class
information_density.py → Phase 2: melodic voice separation
visualizer/            → Next.js app rendering the piano roll + HSL chord colors
```

## Quick Start

### 1. Python Pipeline
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python export_etme_data.py
cp etme_analysis.json visualizer/public/
```

### 2. Next.js Visualizer
```bash
cd visualizer
pnpm install
pnpm dev
# Open http://localhost:3000
```

## How It Works

**4D Chord Coloring**: Each note's color is computed by velocity-weighted vector averaging on a 12-node harmonic color wheel, with 2-second acoustic exponential decay simulating piano sustain resonance.

- **Hue** = angle of the resultant harmonic vector
- **Saturation** = magnitude (tonal purity)
- **Lightness** = octave register (bass=dark, treble=bright)
- **Tonal Distance** = degrees off-center from nearest consonant node
