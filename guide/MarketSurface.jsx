// Market > Surface — 3D Yield Surface viewer
const _ns_ms = window.AtlasNexusDesignSystem_988df3;

function MarketSurface() {
  const { useState } = React;
  const accent = 'var(--accent-cyan)';
  const accentSoft = 'rgba(34,211,238,0.08)';

  const [country, setCountry] = useState('China');
  const [startDate, setStartDate] = useState('2025-06-25');
  const [endDate, setEndDate] = useState('2026-06-25');
  const [viewModes, setViewModes] = useState({ '3D': true, 'Today': false, 'Position': false, 'Short': false, 'Long': false, 'Above': false });

  const toggleMode = (m) => setViewModes(v => ({ ...v, [m]: !v[m] }));

  const COUNTRIES = ['China', 'US'];
  const VIEW_BTNS = ['3D', 'Today', 'Position', 'Short', 'Long', 'Above'];

  // Mini chart placeholder — replicates the 3D surface silhouette
  const SurfacePlaceholder = () => (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      background: 'linear-gradient(160deg, #060d1f 0%, #0a1a3a 60%, #0d1f44 100%)',
      borderRadius: '6px', minHeight: '420px', position: 'relative', overflow: 'hidden',
    }}>
      {/* Grid lines */}
      <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.18 }} preserveAspectRatio="none">
        {[0.2,0.35,0.5,0.65,0.8].map((t,i) => (
          <line key={i} x1={`${t*100}%`} y1="0" x2={`${t*100}%`} y2="100%" stroke="#7ea8cc" strokeWidth="0.8"/>
        ))}
        {[0.25,0.4,0.55,0.7,0.85].map((t,i) => (
          <line key={i} x1="0" y1={`${t*100}%`} x2="100%" y2={`${t*100}%`} stroke="#7ea8cc" strokeWidth="0.8"/>
        ))}
      </svg>
      {/* Surface silhouette */}
      <svg viewBox="0 0 800 400" style={{ width: '92%', height: 'auto', maxHeight: '360px', opacity: 0.85 }} fill="none">
        <defs>
          <linearGradient id="surf1" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f97316" stopOpacity="0.85"/>
            <stop offset="40%" stopColor="#e11d87" stopOpacity="0.75"/>
            <stop offset="100%" stopColor="#7c3aed" stopOpacity="0.55"/>
          </linearGradient>
        </defs>
        <polygon
          points="20,380 80,340 160,300 240,250 320,200 400,160 480,120 560,90 640,70 720,55 780,45 780,380"
          fill="url(#surf1)"
        />
        <polyline
          points="20,340 80,310 160,275 240,230 320,188 400,150 480,115 560,88 640,68 720,52 780,42"
          stroke="rgba(255,255,255,0.35)" strokeWidth="1.2"
        />
        {/* Second ridge */}
        <polygon
          points="20,380 80,370 160,360 240,330 320,310 400,290 480,260 560,240 640,220 720,210 780,200 780,380"
          fill="rgba(124,58,237,0.3)"
        />
      </svg>
      {/* Axis labels */}
      <div style={{ position: 'absolute', bottom: '16px', left: '20px', font: 'var(--type-meta)', color: 'rgba(180,200,230,0.6)', fontSize: '10px' }}>Jan 2025</div>
      <div style={{ position: 'absolute', bottom: '16px', left: '38%', font: 'var(--type-meta)', color: 'rgba(180,200,230,0.6)', fontSize: '10px' }}>Nov 2025</div>
      <div style={{ position: 'absolute', bottom: '16px', left: '70%', font: 'var(--type-meta)', color: 'rgba(180,200,230,0.6)', fontSize: '10px' }}>Jun 2026</div>
      {/* Top-right label */}
      <div style={{ position: 'absolute', top: '14px', right: '18px', font: 'var(--type-meta)', color: 'rgba(230,200,170,0.9)', fontSize: '11px', fontWeight: 600 }}>Today's</div>
      {/* Toolbar top-right */}
      <div style={{ position: 'absolute', top: '12px', left: '14px', display: 'flex', gap: '8px' }}>
        {['⤡','🔍','+','↻','↓','⌂','▦'].map((ic, i) => (
          <div key={i} style={{ width: '26px', height: '26px', borderRadius: '4px', background: 'rgba(255,255,255,0.07)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', fontSize: '12px', color: 'rgba(200,220,255,0.6)' }}>{ic}</div>
        ))}
      </div>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0' }}>
      {/* Chart label */}
      <div style={{ marginBottom: '10px', display: 'flex', alignItems: 'baseline', gap: '10px' }}>
        <span style={{ font: 'var(--type-h3)', color: 'var(--text-primary)' }}>3D Yield Surface</span>
        <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)' }}>{country} · 3D view · through 2026-04-28</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: '16px', alignItems: 'start' }}>

        {/* ── LEFT CONTROL PANEL ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>

          {/* Panel title */}
          <div style={{ padding: '12px 14px 10px', background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px 6px 0 0', borderBottom: 'none' }}>
            <div style={{ font: 'var(--type-h3)', color: 'var(--text-primary)', fontSize: '12px', letterSpacing: '0.06em', textTransform: 'uppercase' }}>Yield Surface Controls</div>
          </div>

          {/* Country Selection */}
          <div style={{ padding: '12px 14px', background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderTop: '1px solid var(--border-default)' }}>
            <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', marginBottom: '8px', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Country</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {COUNTRIES.map(c => (
                <label key={c} onClick={() => setCountry(c)} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                  <div style={{
                    width: '12px', height: '12px', borderRadius: '50%', flexShrink: 0,
                    border: '2px solid ' + (country === c ? accent : 'var(--border-strong)'),
                    background: country === c ? accent : 'transparent',
                    transition: 'all 0.15s',
                  }}></div>
                  <span style={{ font: 'var(--type-label)', color: country === c ? 'var(--text-primary)' : 'var(--text-muted)', fontSize: '11px', transition: 'color 0.15s' }}>{c}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Date Range */}
          <div style={{ padding: '12px 14px', background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderTop: '1px solid var(--border-default)' }}>
            <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', marginBottom: '8px', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Date Range</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <input type="date" value={startDate} onChange={e => setStartDate(e.target.value)} style={{
                width: '100%', boxSizing: 'border-box',
                background: 'var(--surface-input)', border: '1px solid var(--border-default)',
                borderRadius: '4px', padding: '6px 8px', font: 'var(--type-data)', fontSize: '11px',
                color: 'var(--text-primary)', colorScheme: 'dark',
              }} />
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '10px' }}>↓</div>
              <input type="date" value={endDate} onChange={e => setEndDate(e.target.value)} style={{
                width: '100%', boxSizing: 'border-box',
                background: 'var(--surface-input)', border: '1px solid var(--border-default)',
                borderRadius: '4px', padding: '6px 8px', font: 'var(--type-data)', fontSize: '11px',
                color: 'var(--text-primary)', colorScheme: 'dark',
              }} />
            </div>
          </div>

          {/* View Mode */}
          <div style={{ padding: '12px 14px', background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderTop: '1px solid var(--border-default)' }}>
            <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', marginBottom: '8px', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>View Mode</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px' }}>
              {VIEW_BTNS.map(m => {
                const on = viewModes[m];
                return (
                  <button key={m} onClick={() => toggleMode(m)} style={{
                    padding: '6px 8px', font: 'var(--type-label)', fontSize: '10px',
                    border: '1px solid ' + (on ? accent : 'var(--border-default)'),
                    borderRadius: '4px', cursor: 'pointer',
                    background: on ? accentSoft : 'transparent',
                    color: on ? accent : 'var(--text-muted)',
                    transition: 'all 0.15s',
                  }}>{m}</button>
                );
              })}
            </div>
          </div>

          {/* Navigate */}
          <div style={{ padding: '10px 14px', background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderTop: '1px solid var(--border-default)' }}>
            <div style={{ display: 'flex', gap: '6px' }}>
              <button style={{ flex: 1, padding: '7px 10px', font: 'var(--type-label)', fontSize: '10px', border: '1px solid var(--border-default)', borderRadius: '4px', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer' }}>← Back</button>
              <button style={{ flex: 1, padding: '7px 10px', font: 'var(--type-label)', fontSize: '10px', border: '1px solid var(--border-default)', borderRadius: '4px', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer' }}>Next →</button>
            </div>
          </div>

          {/* Refresh + cache note */}
          <div style={{ padding: '10px 14px', background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderTop: '1px solid var(--border-default)', borderRadius: '0 0 6px 6px' }}>
            <button style={{
              width: '100%', padding: '7px 10px', font: 'var(--type-label)', fontSize: '10px',
              border: '1px solid ' + accent, borderRadius: '4px', cursor: 'pointer',
              background: accentSoft, color: accent, transition: 'all 0.15s', marginBottom: '8px',
            }}>↻ Refresh Data</button>
            <div style={{ font: 'var(--type-meta)', color: 'var(--text-faint)', fontSize: '9px', lineHeight: '1.5' }}>
              Cached through <span style={{ color: 'var(--text-muted)' }}>2026-04-28</span> · click Refresh to update
            </div>
          </div>

        </div>

        {/* ── RIGHT: 3D CHART ── */}
        <SurfacePlaceholder />
      </div>
    </div>
  );
}
window.MarketSurface = MarketSurface;
