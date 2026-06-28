// Beta Book > Portfolio — configuration + risk budgets + allocation results
const _ns_bport = window.AtlasNexusDesignSystem_988df3;

const ASSET_POOL = [
  { name:'Silver',  desc:'Precious Metals — N/A', color:'#f59e0b' },
  { name:'Gold',    desc:'Precious Metals — N/A', color:'#f59e0b' },
  { name:'USDCNY',  desc:'USD/CNY — Spot',        color:'#f59e0b' },
  { name:'CN2Y',    desc:'China Gov Bond — 2Y',   color:'#f59e0b' },
  { name:'CN5Y',    desc:'China Gov Bond — 5Y',   color:'#f59e0b' },
];

const RISK_FACTORS = [
  { name:'CMDL.AG',     vol:'57.36%', rpMax:1667, dv01:null, exposure:1667 },
  { name:'CMDL.AU',     vol:'26.39%', rpMax:1667, dv01:null, exposure:1667 },
  { name:'FXDL.USDCNY', vol:'2.38%',  rpMax:1667, dv01:null, exposure:1667 },
  { name:'IRCV.CN',     vol:'0.05%',  rpMax:1286, dv01:0.33, exposure:1286 },
  { name:'IRDL.CN',     vol:'0.12%',  rpMax:1903, dv01:1.38, exposure:1903 },
  { name:'IRSL.CN',     vol:'0.11%',  rpMax:1811, dv01:1.63, exposure:1811 },
];

const ALLOC_ROWS = [
  { assetType:'Commodities', universe:'Base Metals',     sector:'N/A', assetName:'Aluminium', instrument:'Aluminium',   duration:0,    capital:255.00,  dv01:0,      weight:2.56  },
  { assetType:'Commodities', universe:'Precious Metals', sector:'N/A', assetName:'Gold',      instrument:'Gold',        duration:0,    capital:255.00,  dv01:0,      weight:2.56  },
  { assetType:'FX',          universe:'FX Universe',     sector:'N/A', assetName:'USDCNY',    instrument:'USDCNY',      duration:0,    capital:255.00,  dv01:0,      weight:2.56  },
  { assetType:'Rates',       universe:'China Gov Bond',  sector:'1Y',  assetName:'CN1Y',      instrument:'250012.IB',   duration:0.95, capital:3330.00, dv01:0.3164, weight:33.33 },
  { assetType:'Rates',       universe:'China Gov Bond',  sector:'2Y',  assetName:'CN2Y',      instrument:'260006.IB',   duration:1.9,  capital:3140.00, dv01:0.5966, weight:31.44 },
  { assetType:'Rates',       universe:'China Gov Bond',  sector:'5Y',  assetName:'CN5Y',      instrument:'260008.IB',   duration:4.5,  capital:1240.00, dv01:0.558,  weight:12.45 },
  { assetType:'Rates',       universe:'China Gov Bond',  sector:'10Y', assetName:'CN10Y',     instrument:'260010.IB',   duration:8.5,  capital:700.00,  dv01:0.595,  weight:7.03  },
  { assetType:'Rates',       universe:'China Gov Bond',  sector:'20Y', assetName:'CN20Y',     instrument:'2600001.IB',  duration:13,   capital:420.00,  dv01:0.546,  weight:4.23  },
  { assetType:'Rates',       universe:'China Gov Bond',  sector:'30Y', assetName:'CN30Y',     instrument:'2600002.IB',  duration:17,   capital:380.00,  dv01:0.646,  weight:3.84  },
];

function BetaPortfolio() {
  const { useState } = React;
  const [assetType, setAssetType]   = useState('Rates');
  const [capital, setCapital]       = useState('10');
  const [capUnit, setCapUnit]       = useState('Billion');
  const [maxDur, setMaxDur]         = useState('5');
  const [model, setModel]           = useState('Deterministic');
  const [budgetMode, setBudgetMode] = useState('Risk Parity');
  const [hasResults, setHasResults] = useState(true);
  const [open, setOpen]             = useState({ config: true, results: true });
  const [lastRun, setLastRun]       = useState('2026-06-27 20:08:03');

  const accentBlue = 'var(--accent-blue)';
  const accentAmber = 'var(--accent-amber)';

  const toggle = k => setOpen(o => ({ ...o, [k]: !o[k] }));

  function CardHeader({ title, id, badge, action }) {
    return (
      <div
        onClick={() => toggle(id)}
        style={{
          display:'flex', alignItems:'center', justifyContent:'space-between',
          padding:'11px 16px', background:'var(--surface-panel)',
          borderBottom: open[id] ? '1px solid var(--border-strong)' : 'none',
          cursor:'pointer', userSelect:'none',
        }}
      >
        <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
          <span style={{ font:'var(--type-h2)', fontSize:'13px', fontWeight:600, color:'var(--text-primary)' }}>{title}</span>
          {badge && (
            <span style={{ font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)',
              background:'var(--surface-input)', padding:'2px 7px', borderRadius:'3px', border:'1px solid var(--border-default)' }}>
              {badge}
            </span>
          )}
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:'12px' }}>
          {action}
          <span style={{ color:'var(--text-muted)', fontSize:'12px' }}>{open[id] ? '▲' : '▼'}</span>
        </div>
      </div>
    );
  }

  const Radio = ({ value, checked, onChange, label }) => (
    <label style={{ display:'flex', alignItems:'center', gap:'5px', cursor:'pointer',
      font:'var(--type-label)', fontSize:'11px', color: checked ? 'var(--text-primary)' : 'var(--text-muted)' }}>
      <div onClick={onChange} style={{
        width:'12px', height:'12px', borderRadius:'50%', flexShrink:0,
        border:'2px solid ' + (checked ? accentBlue : 'var(--border-strong)'),
        background: checked ? accentBlue : 'transparent', transition:'all 0.15s', cursor:'pointer',
      }}></div>
      <span onClick={onChange}>{label}</span>
    </label>
  );

  const totalCapital = ALLOC_ROWS.reduce((s, r) => s + r.capital, 0);
  const totalDv01    = ALLOC_ROWS.reduce((s, r) => s + r.dv01, 0);
  const totalWeight  = ALLOC_ROWS.reduce((s, r) => s + r.weight, 0);
  const maxDv01      = parseFloat(maxDur) || 0;

  function handleRunAnalysis(e) {
    e.stopPropagation();
    const now = new Date();
    const pad = n => String(n).padStart(2,'0');
    setLastRun(`${now.getFullYear()}-${pad(now.getMonth()+1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`);
    setHasResults(true);
  }

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'10px' }}>

      {/* Page header */}
      <div>
        <h1 style={{ margin:'0 0 4px', font:'var(--type-h1)', color:'var(--text-primary)' }}>Beta Book Portfolio</h1>
        <div style={{ font:'var(--type-meta)', color:'var(--text-muted)' }}>Asset selection · risk budgets · optimised allocation</div>
      </div>

      {/* ── Card 1: Configuration ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <CardHeader title="Configuration" id="config" />
        {open.config && (
          <div>
            {/* Inline config inputs bar */}
            <div style={{
              display:'flex', alignItems:'center', gap:'20px', flexWrap:'wrap',
              padding:'10px 16px', borderBottom:'1px solid var(--border-strong)',
              background:'rgba(255,255,255,0.02)',
            }}>
              <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.06em' }}>Total Capital:</span>
                <input value={capital} onChange={e => setCapital(e.target.value)}
                  style={{ width:'52px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'6px 8px', font:'var(--type-data)', fontSize:'10px', color:'var(--text-primary)', textAlign:'right' }} />
                <select value={capUnit} onChange={e => setCapUnit(e.target.value)}
                  style={{ appearance:'none', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'6px 24px 6px 8px', font:'var(--type-data)', fontSize:'10px', color:'var(--text-primary)', cursor:'pointer' }}>
                  {['Billion','Million'].map(u => <option key={u}>{u}</option>)}
                </select>
                <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px' }}>CNY</span>
              </div>
              <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.06em' }}>Max Dur:</span>
                <input value={maxDur} onChange={e => setMaxDur(e.target.value)}
                  style={{ width:'40px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'6px 8px', font:'var(--type-data)', fontSize:'10px', color:'var(--text-primary)', textAlign:'right' }} />
                <span style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'9px' }}>→ max DV01 {(parseFloat(maxDur)||0).toFixed(1)} MM</span>
              </div>
              <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.06em' }}>Model:</span>
                <div style={{ background:'var(--surface-input)', border:`1px solid ${accentBlue}`, borderRadius:'4px', padding:'5px 10px', font:'var(--type-label)', fontSize:'10px', color: accentBlue, cursor:'pointer' }}>{model}</div>
              </div>
            </div>

            {/* Two-column body */}
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr' }}>

              {/* LEFT — Asset Selection */}
              <div style={{ padding:'16px 18px', borderRight:'1px solid var(--border-strong)' }}>
                <div style={{ font:'var(--type-h2)', fontSize:'13px', fontWeight:600, color:'var(--text-primary)', marginBottom:'12px' }}>Asset Selection</div>
                <div style={{ display:'flex', alignItems:'center', gap:'16px', marginBottom:'14px' }}>
                  <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.06em' }}>Type:</span>
                  <Radio value="Rates" checked={assetType==='Rates'} onChange={() => setAssetType('Rates')} label="Rates" />
                  <Radio value="Cmdty" checked={assetType==='Cmdty'} onChange={() => setAssetType('Cmdty')} label="Cmdty" />
                </div>
                <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'8px' }}>
                  <span style={{ font:'var(--type-label)', color:'var(--text-primary)', fontSize:'10px' }}>
                    Asset Pool <span style={{ color:'var(--text-muted)' }}>({ASSET_POOL.length})</span>
                  </span>
                  <button style={{ padding:'3px 10px', font:'var(--type-label)', fontSize:'10px', background:'rgba(239,68,68,0.15)', color:'#f87171', border:'1px solid rgba(239,68,68,0.3)', borderRadius:'4px', cursor:'pointer' }}>Clear</button>
                </div>
                <div style={{ display:'flex', flexDirection:'column', gap:'4px' }}>
                  {ASSET_POOL.map((a, i) => (
                    <div key={i} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'7px 12px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'5px' }}>
                      <span style={{ font:'var(--type-data)', fontSize:'10px', color: a.color, fontWeight:600 }}>{a.name}</span>
                      <span style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'9px' }}>{a.desc}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* RIGHT — Risk Budgets */}
              <div style={{ padding:'16px 18px' }}>
                <div style={{ display:'flex', alignItems:'baseline', gap:'10px', marginBottom:'10px', flexWrap:'wrap' }}>
                  <span style={{ font:'var(--type-h2)', fontSize:'13px', fontWeight:600, color:'var(--text-primary)' }}>Risk Budgets</span>
                  <span style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'9px' }}>Vol / Risk Parity · Floor 3%, Cap 25%</span>
                </div>
                <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'8px', marginBottom:'10px' }}>
                  Vol from 1Y EWMA · Budget = vol^0.5 · Level &gt; Slope &gt; Curvature
                </div>
                <div style={{ display:'flex', gap:'16px', marginBottom:'12px', flexWrap:'wrap' }}>
                  {['Risk Parity','Factor Model Scaling','User Defined'].map(m => (
                    <Radio key={m} value={m} checked={budgetMode===m} onChange={() => setBudgetMode(m)} label={m} />
                  ))}
                </div>
                <table style={{ width:'100%', borderCollapse:'collapse', font:'var(--type-data)', fontSize:'10px' }}>
                  <thead>
                    <tr style={{ borderBottom:'1px solid var(--border-strong)' }}>
                      {['Factor','Vol %ann','RP Max (MM CNY)','DV01 (MM/bp)','Exposure (MM CNY)'].map(h => (
                        <th key={h} style={{ padding:'5px 8px 5px 0', textAlign: h==='Factor' ? 'left' : 'right', font:'var(--type-label)', fontSize:'8px', color:'var(--text-muted)', letterSpacing:'0.05em', whiteSpace:'nowrap' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {RISK_FACTORS.map((r, i) => (
                      <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.04)' }}>
                        <td style={{ padding:'6px 8px 6px 0', color: accentBlue, fontWeight:600 }}>{r.name}</td>
                        <td style={{ padding:'6px 0', textAlign:'right', color:'var(--text-secondary)' }}>{r.vol}</td>
                        <td style={{ padding:'6px 0', textAlign:'right', color:'var(--text-primary)' }}>{r.rpMax}</td>
                        <td style={{ padding:'6px 0', textAlign:'right', color: r.dv01 ? 'var(--text-secondary)' : 'var(--text-muted)' }}>{r.dv01 ?? '—'}</td>
                        <td style={{ padding:'6px 0', textAlign:'right', color:'var(--text-muted)' }}>{r.exposure}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'8px', marginTop:'10px', textAlign:'right', lineHeight:1.5 }}>
                  Vol auto-refreshes from 1Y EWMA factor history.<br/>Run analysis to refresh RP Max from portfolio decomposition.
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Card 2: Portfolio Allocation Results ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <CardHeader
          title="Portfolio Allocation Results"
          id="results"
          action={
            <button
              onClick={handleRunAnalysis}
              style={{
                padding:'6px 16px', font:'var(--type-label)', fontSize:'10px', fontWeight:700, letterSpacing:'0.06em',
                background: accentBlue, color:'#fff', border:'none', borderRadius:'4px', cursor:'pointer',
              }}
              onMouseEnter={e => e.currentTarget.style.filter='brightness(1.15)'}
              onMouseLeave={e => e.currentTarget.style.filter='brightness(1)'}
            >RUN ANALYSIS</button>
          }
        />

        {open.results && (
          <div style={{ display:'flex', flexDirection:'column' }}>

            {/* Status bar — right-aligned, only when results exist */}
            {hasResults && (
              <div style={{
                padding:'7px 16px', background:'rgba(255,255,255,0.02)', borderBottom:'1px solid var(--border-strong)',
                display:'flex', alignItems:'center', justifyContent:'flex-end', gap:'24px', flexWrap:'wrap',
              }}>
                <span style={{ font:'var(--type-meta)', fontSize:'10px' }}>
                  <span style={{ color:'#34d399' }}>✓ Analysis completed!</span>
                  <span style={{ color:'var(--text-muted)' }}> · </span>
                  <span style={{ color: accentAmber, fontWeight:600 }}>DV01 {totalDv01.toFixed(2)} MM / max {maxDv01.toFixed(2)} MM</span>
                </span>
                <span style={{ font:'var(--type-meta)', fontSize:'10px', color:'var(--text-muted)' }}>Last updated: {lastRun}</span>
              </div>
            )}

            {/* Empty state */}
            {!hasResults && (
              <div style={{ padding:'24px 16px', font:'var(--type-body)', color:'var(--text-muted)', fontSize:'10px' }}>
                No data available. Click 'Run Analysis' to start.
              </div>
            )}

            {/* Results table */}
            {hasResults && (
              <div style={{ overflowX:'auto' }}>
                <table style={{ width:'100%', borderCollapse:'collapse', font:'var(--type-data)', fontSize:'10px' }}>
                  <thead>
                    <tr style={{ background:'var(--surface-panel)', borderBottom:'1px solid var(--border-strong)' }}>
                      {[
                        { label:'ASSET TYPE',           align:'left'  },
                        { label:'UNIVERSE',              align:'left'  },
                        { label:'SECTOR',                align:'left'  },
                        { label:'ASSET NAME',            align:'left'  },
                        { label:'INSTRUMENT',            align:'left'  },
                        { label:'DURATION',              align:'right' },
                        { label:'CAPITAL (MILLION CNY)', align:'right' },
                        { label:'DV01 (MM CNY)',         align:'right' },
                        { label:'WEIGHT',                align:'right' },
                      ].map(h => (
                        <th key={h.label} style={{
                          padding:'7px 10px',
                          textAlign: h.align,
                          font:'var(--type-label)', fontSize:'8px', color:'var(--text-muted)',
                          letterSpacing:'0.05em', whiteSpace:'nowrap',
                        }}>{h.label}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {ALLOC_ROWS.map((r, i) => (
                      <tr key={i} style={{
                        borderBottom:'1px solid rgba(255,255,255,0.04)',
                        background: i%2===0 ? 'transparent' : 'rgba(255,255,255,0.015)',
                      }}>
                        <td style={{ padding:'5px 10px', color:'var(--text-secondary)' }}>{r.assetType}</td>
                        <td style={{ padding:'5px 10px', color:'var(--text-secondary)' }}>{r.universe}</td>
                        <td style={{ padding:'5px 10px', color:'var(--text-muted)' }}>{r.sector}</td>
                        <td style={{ padding:'5px 10px', color:'var(--text-primary)', fontWeight:600 }}>{r.assetName}</td>
                        <td style={{ padding:'5px 10px', color:'var(--text-secondary)', fontSize:'9px', fontFamily:'var(--font-mono, monospace)' }}>{r.instrument}</td>
                        <td style={{ padding:'5px 10px', textAlign:'right', color:'var(--text-secondary)' }}>{r.duration}</td>
                        <td style={{ padding:'5px 10px', textAlign:'right', color:'var(--text-primary)', fontWeight:500 }}>
                          {r.capital.toLocaleString('en-US', { minimumFractionDigits:2, maximumFractionDigits:2 })}
                        </td>
                        <td style={{ padding:'5px 10px', textAlign:'right', color:'var(--text-secondary)' }}>
                          {r.dv01 === 0 ? '0' : r.dv01}
                        </td>
                        <td style={{ padding:'5px 10px', textAlign:'right', color:'var(--text-secondary)' }}>{r.weight.toFixed(2)}%</td>
                      </tr>
                    ))}

                    {/* TOTAL row */}
                    <tr style={{ borderTop:'1px solid var(--border-strong)', background:'rgba(255,255,255,0.03)' }}>
                      <td colSpan={6} style={{ padding:'7px 10px', font:'var(--type-label)', fontSize:'10px', fontWeight:700, color:'var(--text-primary)', letterSpacing:'0.04em' }}>TOTAL</td>
                      <td style={{ padding:'7px 10px', textAlign:'right', fontWeight:700, color:'var(--text-primary)' }}>
                        {totalCapital.toLocaleString('en-US', { minimumFractionDigits:2, maximumFractionDigits:2 })}
                      </td>
                      <td style={{ padding:'7px 10px', textAlign:'right', fontWeight:700, color:'var(--text-primary)' }}>
                        {totalDv01.toFixed(3)}
                      </td>
                      <td style={{ padding:'7px 10px', textAlign:'right', fontWeight:700, color:'var(--text-primary)' }}>
                        {totalWeight.toFixed(2)}%
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            )}

            {/* IRDL Hedge Overlay footer */}
            <div style={{
              padding:'10px 16px', borderTop:'1px solid var(--border-strong)',
              display:'flex', alignItems:'center', gap:'7px',
              font:'var(--type-meta)', fontSize:'10px',
            }}>
              <span style={{
                display:'inline-flex', alignItems:'center', justifyContent:'center',
                width:'17px', height:'17px', borderRadius:'50%',
                border:`1.5px solid ${accentBlue}`, fontSize:'9px', flexShrink:0,
              }}>🛡</span>
              <span style={{ fontFamily:'var(--font-mono, monospace)', color: accentBlue, fontWeight:700, letterSpacing:'0.04em' }}>IRDL</span>
              <span style={{ color: accentAmber, fontWeight:700 }}>Hedge</span>
              <span style={{ color:'var(--text-primary)', fontWeight:600 }}>Overlay</span>
              <span style={{ color:'var(--text-muted)' }}>· optional post-optimisation duration hedge via bond futures or pay-fixed IRS</span>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
window.BetaPortfolio = BetaPortfolio;
