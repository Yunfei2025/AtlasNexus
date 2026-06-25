// Market > Curves — real-time bond curves
const _ns_mc = window.AtlasNexusDesignSystem_988df3;

const CURVE_TYPES = ['China Government Bond', 'China CDB Bond', 'China Corp AAA', 'US Treasury'];
const REF_BONDS = [
  { tenor:'0.3Y', cgb:'269932.IB' }, { tenor:'0.5Y', cgb:'269931.IB' },
  { tenor:'0.7Y', cgb:'260009.IB' }, { tenor:'1Y',   cgb:'250012.IB' },
  { tenor:'1.5Y', cgb:'250017.IB' }, { tenor:'2Y',   cgb:'210007.IB' },
  { tenor:'3Y',   cgb:'240001.IB' }, { tenor:'5Y',   cgb:'250014.IB' },
  { tenor:'10Y',  cgb:'250022.IB' }, { tenor:'20Y',  cgb:'210014.IB' },
  { tenor:'30Y',  cgb:'2500002.IB'},
];

function MarketCurves() {
  const { useState } = React;
  const [curveType, setCurveType] = useState('China Government Bond');

  const LEGEND = [
    { type:'rect', color:'rgba(100,140,200,0.4)', label:'Bid–Offer' },
    { type:'dash', color:'#94a3b8',               label:'Uncertainty' },
    { type:'dot',  color:'#94a3b8',               label:'Mid' },
    { type:'dia',  color:'#34d399',               label:'RT' },
    { type:'rect', color:'#3b82f6',               label:'Ref' },
    { type:'line', color:'#f59e0b',               label:'SpotRate' },
    { type:'line', color:'var(--accent-cyan)',     label:'ForwardRate' },
  ];

  // Spot and forward rate curves
  const TENORS = [0.3,0.5,0.7,1,1.5,2,3,5,7,10];
  const spot  = [1.18,1.19,1.20,1.18,1.22,1.26,1.36,1.55,1.68,1.73];
  const fwd   = [1.31,1.25,1.20,1.20,1.30,1.45,1.65,1.88,2.00,2.00];

  const W=680, H=300, xMin=0, xMax=10, yMin=1.1, yMax=2.1;
  function cx(t){ return ((t-xMin)/(xMax-xMin))*(W-60)+40; }
  function cy(v){ return H-30-((v-yMin)/(yMax-yMin))*(H-50); }

  const spotPath = TENORS.map((t,i)=>`${i===0?'M':'L'}${cx(t).toFixed(1)},${cy(spot[i]).toFixed(1)}`).join(' ');
  const fwdPath  = TENORS.map((t,i)=>`${i===0?'M':'L'}${cx(t).toFixed(1)},${cy(fwd[i]).toFixed(1)}`).join(' ');

  const SNAPSHOT = [
    { label:'10Y Spot',      value:'1.731 %',      large: true },
    { label:'1Y Spot',       value:'1.183 %',      right: { label:'Repo7d-1s5s', value:'+28.9 bp' } },
    { label:'Avg Bid–Ofr',   value:'2.4 bp',       right: { label:'Instruments', value:'65' } },
    { label:'Fwd peak @ Term', value:'2.035 % @ 7.25Y', large: false },
  ];

  return (
    <div style={{ display: 'flex', gap: '16px', alignItems: 'start' }}>

      {/* LEFT SIDEBAR */}
      <div style={{ width: '180px', flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '2px' }}>
        <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px 6px 0 0', borderBottom: 'none', padding: '10px 12px' }}>
          <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '6px' }}>Curve Type</div>
          <div style={{ position: 'relative' }}>
            <select value={curveType} onChange={e => setCurveType(e.target.value)} style={{
              appearance: 'none', WebkitAppearance: 'none', width: '100%',
              background: 'var(--surface-input)', border: '1px solid var(--border-default)',
              borderRadius: '4px', padding: '6px 24px 6px 8px', font: 'var(--type-data)', fontSize: '10px',
              color: 'var(--text-primary)', cursor: 'pointer',
            }}>
              {CURVE_TYPES.map(c => <option key={c}>{c}</option>)}
            </select>
            <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ position: 'absolute', right: '6px', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}>
              <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </div>
        </div>

        <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '0 0 6px 6px', borderTop: '1px solid var(--border-default)', padding: '10px 0' }}>
          <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.07em', padding: '0 12px', marginBottom: '6px' }}>Reference Bonds</div>
          <table style={{ width: '100%', borderCollapse: 'collapse', font: 'var(--type-data)', fontSize: '10px' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border-default)' }}>
                {['TENOR','CGB'].map(h => (
                  <th key={h} style={{ padding: '4px 12px', textAlign: h==='TENOR'?'left':'right', font: 'var(--type-label)', fontSize: '8px', color: 'var(--text-muted)', letterSpacing: '0.06em' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {REF_BONDS.map((r,i) => (
                <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                  <td style={{ padding: '4px 12px', color: 'var(--text-muted)', fontWeight: 500 }}>{r.tenor}</td>
                  <td style={{ padding: '4px 12px', textAlign: 'right', color: 'var(--text-secondary)' }}>{r.cgb}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* CENTER CHART */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px', minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
          <span style={{ font: 'var(--type-h3)', color: 'var(--text-primary)' }}>Real Time Bond Curves</span>
          <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)' }}>{curveType} · 2026-06-26 00:34:02</span>
        </div>

        {/* Legend */}
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', padding: '5px 10px', background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '5px' }}>
          {LEGEND.map(({color, label}) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: '5px', font: 'var(--type-meta)', color: 'var(--text-secondary)', fontSize: '10px' }}>
              <div style={{ width: '14px', height: '2px', background: color, borderRadius: '1px' }}></div>
              {label}
            </div>
          ))}
        </div>

        {/* Chart */}
        <div style={{ background: '#071428', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '10px' }}>
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 'auto' }} preserveAspectRatio="xMidYMid meet">
            {/* Grid */}
            {[1.2,1.4,1.6,1.8,2.0].map((v,i) => (
              <g key={i}>
                <line x1="40" y1={cy(v)} x2={W-10} y2={cy(v)} stroke="rgba(100,140,200,0.12)" strokeWidth="0.8"/>
                <text x="35" y={cy(v)+4} textAnchor="end" fontSize="9" fill="rgba(150,180,220,0.6)">{v.toFixed(1)}</text>
              </g>
            ))}
            {/* X axis labels */}
            {[0,2,4,6,8,10].map((t,i) => (
              <text key={i} x={cx(t)} y={H-8} textAnchor="middle" fontSize="9" fill="rgba(150,180,220,0.6)">{t}</text>
            ))}
            <text x={W/2} y={H} textAnchor="middle" fontSize="9" fill="rgba(150,180,220,0.5)">Tenor (years)</text>
            <text x="12" y={H/2} textAnchor="middle" fontSize="9" fill="rgba(150,180,220,0.5)" transform={`rotate(-90,12,${H/2})`}>Yield (%)</text>

            {/* Bid-offer shaded band */}
            {TENORS.map((t,i) => i < TENORS.length-1 && (
              <rect key={i} x={cx(t)-3} y={cy(spot[i]+0.02)} width="6" height={Math.abs(cy(spot[i]+0.02)-cy(spot[i]-0.02))} fill="rgba(100,140,210,0.25)" rx="1"/>
            ))}

            {/* Scatter dots — RT (green diamonds) */}
            {TENORS.map((t,i) => {
              const nx = cx(t) + (Math.sin(i*7)*5);
              const ny = cy(spot[i]) + (Math.cos(i*5)*4);
              return <polygon key={i} points={`${nx},${ny-5} ${nx+4},${ny} ${nx},${ny+5} ${nx-4},${ny}`} fill="#34d399" opacity="0.85"/>;
            })}
            {/* Ref dots (blue squares) */}
            {TENORS.map((t,i) => (
              <rect key={i} x={cx(t)+6} y={cy(spot[i])-4} width="8" height="8" fill="#3b82f6" opacity="0.7"/>
            ))}

            {/* Spot rate (amber) */}
            <path d={spotPath} stroke="#f59e0b" strokeWidth="2" fill="none"/>
            {/* Forward rate (cyan) */}
            <path d={fwdPath} stroke="var(--accent-cyan)" strokeWidth="1.8" fill="none"/>
          </svg>
        </div>
      </div>

      {/* RIGHT SNAPSHOT */}
      <div style={{ width: '160px', flexShrink: 0, background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '14px 14px' }}>
        <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '14px' }}>Curve Snapshot</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <div>
            <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', fontSize: '9px', marginBottom: '3px' }}>10Y Spot</div>
            <div style={{ font: 'var(--type-data)', color: 'var(--text-primary)', fontSize: '20px', fontWeight: 700, letterSpacing: '-0.01em' }}>1.731 %</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', fontSize: '9px', marginBottom: '2px' }}>1Y Spot</div>
              <div style={{ font: 'var(--type-data)', color: 'var(--text-primary)', fontSize: '13px', fontWeight: 600 }}>1.183 %</div>
            </div>
            <div>
              <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', fontSize: '9px', marginBottom: '2px' }}>Repo7d-1s5s</div>
              <div style={{ font: 'var(--type-data)', color: '#34d399', fontSize: '13px', fontWeight: 600 }}>+28.9 bp</div>
            </div>
          </div>
          <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: '10px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
            <div>
              <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', fontSize: '9px', marginBottom: '2px' }}>Avg Bid–Ofr</div>
              <div style={{ font: 'var(--type-data)', color: 'var(--text-primary)', fontSize: '13px', fontWeight: 600 }}>2.4 bp</div>
            </div>
            <div>
              <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', fontSize: '9px', marginBottom: '2px' }}>Instruments</div>
              <div style={{ font: 'var(--type-data)', color: 'var(--text-primary)', fontSize: '13px', fontWeight: 600 }}>65</div>
            </div>
          </div>
          <div style={{ borderTop: '1px solid var(--border-default)', paddingTop: '10px' }}>
            <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', fontSize: '9px', marginBottom: '3px' }}>Fwd peak @ Term</div>
            <div style={{ font: 'var(--type-data)', color: 'var(--accent-cyan)', fontSize: '13px', fontWeight: 600 }}>2.035 % @ 7.25Y</div>
          </div>
        </div>
      </div>

    </div>
  );
}
window.MarketCurves = MarketCurves;
