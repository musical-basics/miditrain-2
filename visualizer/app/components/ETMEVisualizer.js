'use client';

import { useRef, useState, useEffect, useCallback } from 'react';

// ===== CONSTANTS =====
const PITCH_MIN = 21;
const PITCH_MAX = 108;
const MAX_CANVAS_PX = 16000;
const RULER_HEIGHT = 24;
const NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
const BLACK_KEYS = [1,3,6,8,10];

// Format ms to "M:SS.s" timestamp
function formatTime(ms) {
  const totalSec = ms / 1000;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return min > 0 ? `${min}:${sec.toFixed(1).padStart(4, '0')}` : `${sec.toFixed(1)}s`;
}

// ===== COLOR HELPERS =====
function hsl(h, s, l, a = 1) {
  return `hsla(${h}, ${s}%, ${l}%, ${a})`;
}

function idScoreToColor(score) {
  const t = Math.min(score / 120, 1);
  const h = 240 - t * 240;
  const s = 70 + t * 20;
  const l = 45 + t * 15;
  return hsl(h, s, l);
}

function regimeBlockColor(regime) {
  const h = regime.hue || 0;
  const s = regime.saturation || 0;
  if (regime.state === 'Silence') return { bg: 'rgba(30,30,40,0.3)', border: 'rgba(80,80,100,0.2)', label: 'Silence' };
  if (regime.state === 'Undefined / Gray Void') return { bg: 'rgba(60,60,80,0.1)', border: 'rgba(100,100,130,0.15)', label: 'Void' };
  if (regime.state === 'TRANSITION SPIKE!') return { bg: `hsla(${h},90%,50%,0.06)`, border: `hsla(${h},90%,60%,0.35)`, label: '⚡ Spike' };
  if (regime.state === 'Regime Locked') return { bg: `hsla(${h},${Math.min(s,80)}%,40%,0.08)`, border: `hsla(${h},${Math.min(s,80)}%,55%,0.3)`, label: '🔒 Locked' };
  return { bg: `hsla(${h},${Math.min(s,70)}%,45%,0.04)`, border: `hsla(${h},${Math.min(s,70)}%,55%,0.15)`, label: 'Stable' };
}

// ===== MAIN COMPONENT =====
export default function ETMEVisualizer() {
  const canvasRef = useRef(null);
  const wrapperRef = useRef(null);
  const keyboardRef = useRef(null);

  const [data, setData] = useState(null);
  const [currentView, setCurrentView] = useState('raw');
  const [hZoom, setHZoom] = useState(10);
  const [vZoom, setVZoom] = useState(10);
  const [tooltip, setTooltip] = useState(null);

  const effectiveScaleRef = useRef(0.05);

  // Load data on mount
  useEffect(() => {
    fetch(`/etme_analysis.json?t=${Date.now()}`)
      .then(r => r.json())
      .then(setData)
      .catch(err => console.error('Failed to load data:', err));
  }, []);

  // Sync scroll between keyboard and canvas
  useEffect(() => {
    const wrapper = wrapperRef.current;
    const keyboard = keyboardRef.current;
    if (!wrapper || !keyboard) return;
    const onScroll = () => { keyboard.scrollTop = wrapper.scrollTop; };
    wrapper.addEventListener('scroll', onScroll);
    return () => wrapper.removeEventListener('scroll', onScroll);
  }, []);

  // Rendering
  const noteHeight = vZoom;
  const msPxInput = 0.005 * hZoom;

  const render = useCallback(() => {
    if (!data || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d');
    const notes = data.notes;
    const regimes = data.regimes;
    const pitchRange = PITCH_MAX - PITCH_MIN + 1;

    const maxTime = Math.max(...notes.map(n => n.onset + n.duration)) + 500;
    const effectiveScale = msPxInput;
    effectiveScaleRef.current = effectiveScale;
    const canvasW = Math.min(Math.max(maxTime * effectiveScale, 1200), MAX_CANVAS_PX);
    const rollH = pitchRange * noteHeight;
    const canvasH = rollH + RULER_HEIGHT;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = canvasW * dpr;
    canvas.height = canvasH * dpr;
    canvas.style.width = canvasW + 'px';
    canvas.style.height = canvasH + 'px';
    ctx.scale(dpr, dpr);

    // Background
    ctx.fillStyle = '#0d0d12';
    ctx.fillRect(0, 0, canvasW, canvasH);

    // Grid rows
    for (let p = PITCH_MIN; p <= PITCH_MAX; p++) {
      const y = (PITCH_MAX - p) * noteHeight;
      const pc = p % 12;
      const isBlack = BLACK_KEYS.includes(pc);
      ctx.fillStyle = isBlack ? 'rgba(255,255,255,0.015)' : 'transparent';
      ctx.fillRect(0, y, canvasW, noteHeight);
      ctx.strokeStyle = 'rgba(255,255,255,0.04)';
      ctx.lineWidth = 0.5;
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvasW, y); ctx.stroke();
    }

    // Beat grid + timestamp ruler
    ctx.fillStyle = '#111118';
    ctx.fillRect(0, rollH, canvasW, RULER_HEIGHT);
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, rollH); ctx.lineTo(canvasW, rollH); ctx.stroke();

    for (let t = 0; t < maxTime; t += 100) {
      const x = t * effectiveScale;
      // Vertical grid lines: fine (100ms), semi-major (500ms), major (1000ms)
      if (t % 1000 === 0) {
        ctx.strokeStyle = 'rgba(255,255,255,0.12)';
        ctx.lineWidth = 1;
      } else if (t % 500 === 0) {
        ctx.strokeStyle = 'rgba(255,255,255,0.07)';
        ctx.lineWidth = 0.75;
      } else {
        ctx.strokeStyle = 'rgba(255,255,255,0.03)';
        ctx.lineWidth = 0.5;
      }
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, rollH); ctx.stroke();

      // Ruler tick marks
      const isMajor = t % 1000 === 0;
      const isMid = t % 500 === 0;
      if (isMajor || isMid) {
        const tickH = isMajor ? 8 : 4;
        ctx.strokeStyle = 'rgba(255,255,255,0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, rollH); ctx.lineTo(x, rollH + tickH); ctx.stroke();
      }
      // Labels every 1s
      if (isMajor) {
        ctx.font = '9px Inter';
        ctx.fillStyle = 'rgba(255,255,255,0.45)';
        ctx.textAlign = 'center';
        ctx.fillText(formatTime(t), x, rollH + 18);
        ctx.textAlign = 'start';
      }
    }

    // Phase 1: Regime blocks — paint background using the TRUE average chord hue from notes
    if (currentView === 'phase1') {
      for (const r of regimes) {
        const x = r.start_time * effectiveScale;
        const w = Math.max((r.end_time - r.start_time) * effectiveScale, 1);

        // Compute average hue from all notes within this regime's time window
        const notesInRegime = notes.filter(n => n.onset >= r.start_time && n.onset < r.end_time);
        let avgHue = 0, avgSat = 0;

        if (notesInRegime.length > 0) {
          // Vector-average the hues (to handle wraparound at 360°)
          let sinSum = 0, cosSum = 0, satSum = 0;
          for (const n of notesInRegime) {
            const rad = (n.hue || 0) * Math.PI / 180;
            sinSum += Math.sin(rad);
            cosSum += Math.cos(rad);
            satSum += (n.sat || 0);
          }
          avgHue = Math.atan2(sinSum, cosSum) * 180 / Math.PI;
          if (avgHue < 0) avgHue += 360;
          avgSat = satSum / notesInRegime.length;
        }

        // Background fill: regime's true harmonic color, very faint
        if (r.state === 'Silence' || r.state === 'Undefined / Gray Void') {
          ctx.fillStyle = 'rgba(30,30,40,0.15)';
        } else {
          ctx.fillStyle = `hsla(${avgHue}, ${Math.min(avgSat, 80)}%, 45%, 0.06)`;
        }
        ctx.fillRect(x, 0, w, rollH);

        // Vertical separator line in the same hue
        ctx.strokeStyle = `hsla(${avgHue}, ${Math.min(avgSat, 70)}%, 55%, 0.15)`;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, rollH); ctx.stroke();

        // Thin 3px state indicator bar at the very top
        let stateColor, stateLabel;
        if (r.state === 'TRANSITION SPIKE!') {
          stateColor = `hsla(60, 95%, 60%, 0.8)`;
          stateLabel = '⚡ Spike';
        } else if (r.state === 'Regime Locked') {
          stateColor = `hsla(120, 80%, 50%, 0.8)`;
          stateLabel = '🔒 Locked';
        } else if (r.state === 'Silence' || r.state === 'Undefined / Gray Void') {
          stateColor = `rgba(80, 80, 100, 0.4)`;
          stateLabel = r.state === 'Silence' ? 'Silence' : 'Void';
        } else {
          stateColor = `hsla(${avgHue}, 70%, 55%, 0.6)`;
          stateLabel = 'Stable';
        }
        ctx.fillStyle = stateColor;
        ctx.fillRect(x, 0, w, 3);

        // Label
        if (w > 30) {
          ctx.font = '9px Inter';
          ctx.fillStyle = stateColor;
          ctx.fillText(stateLabel, x + 4, 14);
        }
      }
    }

    // Draw notes
    for (const n of notes) {
      const x = n.onset * effectiveScale;
      const w = Math.max(n.duration * effectiveScale, 2);
      const y = (PITCH_MAX - n.pitch) * noteHeight;

      let fillColor, strokeColor;

      if (currentView === 'raw') {
        const velAlpha = 0.4 + (n.velocity / 127) * 0.6;
        fillColor = hsl(220, 70, 60, velAlpha);
        strokeColor = hsl(220, 80, 70, 0.7);
      } else if (currentView === 'phase1') {
        // 4D chord color: Hue from vector angle, Sat from magnitude, Lightness from octave
        const h = n.hue || 0;
        const s = Math.min(n.sat || 30, 100);
        // Remap lightness to a wider visual range (20-80) for better contrast
        const rawL = n.lightness || 50;
        const l = 20 + (rawL / 100) * 60;

        if (n.regime_state === 'TRANSITION SPIKE!') {
          fillColor = `hsla(${h}, ${Math.max(s, 70)}%, ${l}%, 0.95)`;
          strokeColor = `hsla(${h}, 95%, ${Math.min(l + 15, 85)}%, 1)`;
          ctx.shadowColor = `hsla(${h}, 90%, 50%, 0.4)`;
          ctx.shadowBlur = 4;
        } else if (n.regime_state === 'Regime Locked') {
          fillColor = `hsla(${h}, ${s}%, ${l}%, 0.9)`;
          strokeColor = `hsla(${h}, ${s}%, ${Math.min(l + 10, 80)}%, 0.95)`;
        } else if (n.regime_state === 'Silence' || n.regime_state === 'Undefined / Gray Void') {
          fillColor = `rgba(80, 80, 100, 0.4)`;
          strokeColor = `rgba(100, 100, 130, 0.6)`;
        } else {
          fillColor = `hsla(${h}, ${s}%, ${l}%, 0.8)`;
          strokeColor = `hsla(${h}, ${s}%, ${Math.min(l + 10, 80)}%, 0.9)`;
        }
      } else if (currentView === 'phase2') {
        fillColor = idScoreToColor(n.id_score);
        strokeColor = idScoreToColor(n.id_score);
        if (n.voice_tag && n.voice_tag.includes('Voice 1')) {
          ctx.shadowColor = 'rgba(236, 72, 153, 0.5)';
          ctx.shadowBlur = 6;
        } else {
          ctx.shadowColor = 'transparent';
          ctx.shadowBlur = 0;
        }
      }

      ctx.fillStyle = fillColor;
      ctx.beginPath();
      ctx.roundRect(x, y + 1, w, noteHeight - 2, 2);
      ctx.fill();
      ctx.strokeStyle = strokeColor;
      ctx.lineWidth = 0.5;
      ctx.stroke();
      ctx.shadowColor = 'transparent';
      ctx.shadowBlur = 0;
    }
  }, [data, currentView, msPxInput, noteHeight]);

  useEffect(() => { render(); }, [render]);

  // Tooltip handler
  const handleMouseMove = useCallback((e) => {
    if (!data) return;
    const rect = canvasRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const timeMs = mx / effectiveScaleRef.current;
    const pitch = PITCH_MAX - Math.floor(my / noteHeight);

    const hit = data.notes.find(n =>
      pitch === n.pitch && timeMs >= n.onset && timeMs <= n.onset + n.duration
    );

    if (hit) {
      const noteName = NOTE_NAMES[hit.pitch % 12] + (Math.floor(hit.pitch / 12) - 1);
      setTooltip({
        x: e.clientX + 14,
        y: e.clientY + 14,
        noteName, pitch: hit.pitch, velocity: hit.velocity,
        onset: hit.onset, duration: hit.duration,
        id_score: hit.id_score, voice_tag: hit.voice_tag,
        hue: hit.hue, sat: hit.sat, lightness: hit.lightness, tonal_distance: hit.tonal_distance
      });
    } else {
      setTooltip(null);
    }
  }, [data, noteHeight]);

  // Keyboard
  const keyboardKeys = [];
  for (let p = PITCH_MAX; p >= PITCH_MIN; p--) {
    const pc = p % 12;
    const octave = Math.floor(p / 12) - 1;
    const isBlack = BLACK_KEYS.includes(pc);
    const isC = pc === 0;
    keyboardKeys.push(
      <div
        key={p}
        className={`key ${isBlack ? 'black' : 'white'} ${isC ? 'c-note' : ''}`}
        style={{ height: noteHeight }}
      >
        {isC ? `C${octave}` : ''}
      </div>
    );
  }

  // Legend
  const legendContent = () => {
    if (currentView === 'raw') return (
      <>
        <h3>Piano Roll</h3>
        <div className="legend-item"><div className="legend-swatch" style={{ background: hsl(220,70,60,0.5) }} />Quiet Note</div>
        <div className="legend-item"><div className="legend-swatch" style={{ background: hsl(220,70,60,1) }} />Loud Note</div>
      </>
    );
    if (currentView === 'phase1') return (
      <>
        <h3>Phase 1 — Harmonic Regimes</h3>
        <div className="legend-item"><div className="legend-swatch" style={{ background: 'hsla(0,70%,45%,0.6)' }} />Stable (by hue)</div>
        <div className="legend-item"><div className="legend-swatch" style={{ background: 'hsla(120,80%,50%,0.75)' }} />🔒 Locked</div>
        <div className="legend-item"><div className="legend-swatch" style={{ background: 'hsla(60,95%,60%,0.9)', boxShadow: '0 0 6px hsla(60,90%,50%,0.5)' }} />⚡ Spike</div>
        <div className="legend-item"><div className="legend-swatch" style={{ background: 'rgba(80,80,100,0.4)' }} />Silence / Void</div>
      </>
    );
    return (
      <>
        <h3>Phase 2 — Information Density</h3>
        <div className="legend-item"><div className="legend-swatch" style={{ background: hsl(240,70,45) }} />Low I<sub>d</sub> (Background)</div>
        <div className="legend-item"><div className="legend-swatch" style={{ background: hsl(120,80,52) }} />Medium I<sub>d</sub></div>
        <div className="legend-item"><div className="legend-swatch" style={{ background: hsl(0,90,60), boxShadow: '0 0 8px rgba(236,72,153,0.5)' }} />High I<sub>d</sub> (Melody)</div>
      </>
    );
  };

  const views = [
    { id: 'raw', label: 'Piano Roll', color: 'var(--accent-blue)' },
    { id: 'phase1', label: 'Phase 1 — Harmonic Regimes', color: 'var(--accent-green)' },
    { id: 'phase2', label: 'Phase 2 — Information Density', color: 'var(--accent-pink)' },
  ];

  return (
    <>
      {/* HEADER */}
      <div className="header">
        <h1><span>ETME</span> Visualizer</h1>
        <div className="stats">
          <div>Notes<span className="stat-value">{data?.stats?.total_notes ?? '—'}</span></div>
          <div>Regimes<span className="stat-value">{data?.stats?.total_regimes ?? '—'}</span></div>
          <div>Melody<span className="stat-value">{data?.stats?.melody_notes ?? '—'}</span></div>
          <div>Background<span className="stat-value">{data?.stats?.background_notes ?? '—'}</span></div>
        </div>
      </div>

      {/* TABS */}
      <div className="view-tabs">
        {views.map(v => (
          <button
            key={v.id}
            className={`view-tab ${currentView === v.id ? 'active' : ''}`}
            onClick={() => setCurrentView(v.id)}
          >
            <span className="dot" style={{ background: v.color }} />
            {v.label}
          </button>
        ))}
      </div>

      {/* ZOOM */}
      <div className="zoom-bar">
        <div className="zoom-group">
          <label>H-Zoom</label>
          <input type="range" min="1" max="100" value={hZoom} onChange={e => setHZoom(+e.target.value)} />
          <span className="zoom-value">{hZoom}</span>
        </div>
        <div className="zoom-group">
          <label>V-Zoom</label>
          <input type="range" min="4" max="30" value={vZoom} onChange={e => setVZoom(+e.target.value)} />
          <span className="zoom-value">{vZoom}</span>
        </div>
      </div>

      {/* PIANO ROLL */}
      <div className="roll-container">
        <div className="keyboard" ref={keyboardRef}>{keyboardKeys}</div>
        <div className="canvas-wrapper" ref={wrapperRef}>
          <canvas
            ref={canvasRef}
            onMouseMove={handleMouseMove}
            onMouseLeave={() => setTooltip(null)}
          />
        </div>
      </div>

      {/* LEGEND */}
      <div className="legend">{legendContent()}</div>

      {/* TOOLTIP */}
      {tooltip && (
        <div className="tooltip" style={{ display: 'block', left: tooltip.x, top: tooltip.y }}>
          <div className="tt-label">{tooltip.noteName} (MIDI {tooltip.pitch})</div>
          <div className="tt-detail">
            Velocity: {tooltip.velocity}<br />
            Onset: {tooltip.onset}ms<br />
            Duration: {tooltip.duration}ms<br />
            <br />
            <strong>4D Chord Color:</strong><br />
            H: {tooltip.hue}° | S: {tooltip.sat}% | L: {tooltip.lightness}%<br />
            Tension: {tooltip.tonal_distance}°<br />
            <br />
            I<sub>d</sub> Score: {tooltip.id_score}<br />
            Tag: {tooltip.voice_tag}
          </div>
        </div>
      )}
    </>
  );
}
