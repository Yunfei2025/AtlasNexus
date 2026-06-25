// Market > Trend — series trend chart with quick-select sidebar
const _ns_mt = window.AtlasNexusDesignSystem_988df3;

const TREND_SERIES = [
  '1Y Tsy','5Y Tsy','10Y Tsy','30Y Tsy',
  '5s1s','10s5s','30s10s',
  'IRS 1Y','IRS 2Y','IRS 5Y','IRS 2s1s','IRS 5s2s','IRS 5s1s',
  'BdSwap 1Y','BdSwap 2Y','BdSwap 5Y',
];

function MarketTrend() {
  const { useState } = React;
  const [selected, setSelected] = useState('10Y Tsy');
  const accent = 'var(--accent-cyan)';

  // Mini sparkline generator
  function Spark({ color, label, points, height = 60 }) {
    const w = 220, h = height;
    const mn = Math.min(...points), mx = Math.max(...points);
    const r = mx - mn || 1;
    const pts = points.map((v, i) => `${(i / (points.length - 1)) * w},${h - ((v - mn) / r) * (h - 8) - 4}`).join(' ');
    return (
      <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '10px 12px', flex: '1 1 200px', minWidth: '180px' }}>
        <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginBottom: '6px', fontSize: '10px' }}>{label}</div>
        <svg viewBox={`0 0 ${w} ${h}`} style={{ width: '100%', height: `${h}px` }} preserveAspectRatio="none">
          <polyline points={pts} stroke={color} strokeWidth="1.5" fill="none" />
        </svg>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '4px', font: 'var(--type-meta)', color: 'var(--text-muted)', fontSize: '9px' }}>
          <span>Jul 2025</span><span>Jun 2026</span>
        </div>
      </div>
    );
  }

  // Pseudo-random data seeded by series name
  function seed(s) { let h=0; for(let c of s){h=((h<<5)-h+c.charCodeAt(0))|0;} return Math.abs(h); }
  function genPoints(s, n=80, base=1.75, amp=0.15) {
    let v = base, arr = [], r = seed(s);
    for(let i=0;i<n;i++){r=(r*1664525+1013904223)&0xffffffff; v+=((r/0xffffffff)-0.5)*amp*0.3; arr.push(Math.max(base-amp,Math.min(base+amp,v)));}
    return arr;
  }

  const mainPts = genPoints(selected);
  const trendPts = mainPts.map((v,i)=>v+0.005*(i/mainPts.length));

  // Chart SVG
  const W=700, H=220;
  const allPts=[...mainPts,...trendPts];
  const mn=Math.min(...allPts)-0.02, mx=Math.max(...allPts)+0.02, rng=mx-mn;
  function px(v,i,n,w){ return { x:(i/(n-1))*w, y:H-((v-mn)/rng)*(H-20)-10 }; }
  const seriesPath = mainPts.map((v,i)=>{const p=px(v,i,mainPts.length,W);return `${i===0?'M':'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;}).join(' ');
  const trendPath  = trendPts.map((v,i)=>{const p=px(v,i,trendPts.length,W);return `${i===0?'M':'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`;}).join(' ');

  const funding = [
    { label:'FR001.IR', pts: genPoints('FR001',80,1.55,0.15), color:'var(--accent-cyan)' },
    { label:'FR007.IR', pts: genPoints('FR007',80,1.60,0.20), color:'var(--accent-cyan)' },
    { label:'SHIBOR3M.IR', pts: genPoints('SHI3M',80,1.50,0.12), color:'var(--accent-cyan)' },
  ];
  const factors = [
    { label:'level',     pts: genPoints('level',80,2.3,0.4),   color:'var(--accent-amber)' },
    { label:'slope',     pts: genPoints('slope',80,-1.0,0.4),  color:'var(--accent-amber)' },
    { label:'curvature', pts: genPoints('curv',80,-1.0,0.4),   color:'var(--accent-amber)' },
  ];

  const LEGEND = [
    { color:'#e84040', label:'Series' },
    { color:'var(--accent-cyan)', label:'Trend Line' },
    { color:'#f59e0b', label:'Local Max' },
    { color:'#34d399', label:'Local Min' },
    { color:'#e84040', label:'Downward Conf.' },
    { color:'#818cf8', label:'Upward Conf.' },
  ];

  return (
    <div style={{ display: 'flex', gap: '16px', alignItems: 'start' }}>

      {/* LEFT SIDEBAR */}
      <div style={{ width: '160px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '2px' }}>
        {/* Series dropdown */}
        <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px 6px 0 0', borderBottom: 'none', padding: '10px 12px' }}>
          <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '6px' }}>Series</div>
          <div style={{ background: 'var(--surface-input)', border: '1px solid var(--border-default)', borderRadius: '4px', padding: '6px 10px', font: 'var(--type-data)', fontSize: '11px', color: 'var(--text-primary)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', cursor: 'pointer' }}>
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{selected}</span>
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
          </div>
        </div>
        {/* Quick select */}
        <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '0 0 6px 6px', borderTop: '1px solid var(--border-default)', padding: '10px 12px' }}>
          <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '6px' }}>Quick Select</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
            {TREND_SERIES.map(s => (
              <button key={s} onClick={() => setSelected(s)} style={{
                padding: '5px 8px', font: 'var(--type-label)', fontSize: '10px', textAlign: 'left',
                border: 'none', borderRadius: '3px', cursor: 'pointer',
                background: selected === s ? accent : 'transparent',
                color: selected === s ? 'var(--text-on-accent)' : 'var(--text-secondary)',
                transition: 'all 0.12s',
              }}>{s}</button>
            ))}
          </div>
        </div>
      </div>

      {/* MAIN CONTENT */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px', minWidth: 0 }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
          <span style={{ font: 'var(--type-h3)', color: 'var(--text-primary)' }}>{selected}</span>
          <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)' }}>Updated 00:34:02</span>
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', padding: '6px 12px', background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '5px' }}>
          {LEGEND.map(({color, label}) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '5px', font: 'var(--type-meta)', color: 'var(--text-secondary)', fontSize: '10px' }}>
              <div style={{ width: '18px', height: '2px', background: color, borderRadius: '1px' }}></div>
              {label}
            </div>
          ))}
        </div>

        {/* Main chart */}
        <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '14px 16px' }}>
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} preserveAspectRatio="xMidYMid meet">
            {/* Grid */}
            {[0.2,0.4,0.6,0.8].map((t,i) => (
              <line key={i} x1="0" y1={H*t} x2={W} y2={H*t} stroke="rgba(100,130,180,0.15)" strokeWidth="0.8"/>
            ))}
            <path d={trendPath} stroke="var(--accent-cyan)" strokeWidth="1.5" fill="none" strokeDasharray="4,3" opacity="0.8"/>
            <path d={seriesPath} stroke="#e84040" strokeWidth="1.2" fill="none" opacity="0.9"/>
            {/* Markers - Local Max */}
            {[15,28,42].map(i => {
              const p = px(mainPts[i],i,mainPts.length,W);
              return <polygon key={i} points={`${p.x},${p.y-8} ${p.x-5},${p.y+1} ${p.x+5},${p.y+1}`} fill="#f59e0b" opacity="0.9"/>;
            })}
            {/* Markers - Local Min */}
            {[20,35,55].map(i => {
              const p = px(mainPts[i],i,mainPts.length,W);
              return <polygon key={i} points={`${p.x},${p.y+8} ${p.x-5},${p.y-1} ${p.x+5},${p.y-1}`} fill="#34d399" opacity="0.9"/>;
            })}
          </svg>
          <div style={{ display: 'flex', justifyContent: 'space-between', font: 'var(--type-meta)', color: 'var(--text-muted)', fontSize: '9px', marginTop: '6px' }}>
            <span>Jul 2025</span><span>Sep 2025</span><span>Nov 2025</span><span>Jan 2026</span><span>Mar 2026</span><span>May 2026</span><span>Jul 2026</span>
          </div>
        </div>

        {/* Funding Rates row */}
        <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.07em' }}>Funding Rates</div>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          {funding.map(f => <Spark key={f.label} label={f.label} points={f.pts} color={f.color} />)}
        </div>

        {/* Yield Curve Factors row */}
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          {factors.map(f => <Spark key={f.label} label={f.label} points={f.pts} color={f.color} height={70} />)}
        </div>
      </div>
    </div>
  );
}
window.MarketTrend = MarketTrend;
