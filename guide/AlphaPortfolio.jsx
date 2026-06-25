// Alpha Book > Portfolio — 3-card workflow
const _ns_ap = window.AtlasNexusDesignSystem_988df3;

const STEP3_ROWS = [
  { id:'CDBCGB-30y', type:'TenorSpread', leg1:'210221.IB',   leg2:'2600002.IB',  regime:'momentum',     dir:'BUY',  z:-0.8949, spread:11.02,  mean:13.3113,  vol:2.5604,  hl:null,   cr:-17.755,  be:0.5918, stop:0.3499, target:0.5065, score:20.6063, wt:0.0152 },
  { id:'Repo7d-6m1y',type:'SwapSpread',  leg1:'FR007S1Y.IR', leg2:'FR007S6M.IR', regime:'momentum',     dir:'BUY',  z:-0.0089, spread:-0.25,  mean:-0.1854,  vol:7.2704,  hl:null,   cr:-0.3,     be:0.3,    stop:0.9061, target:0.9101, score:3.7801,  wt:0.0152 },
  { id:'CGB-10s30s', type:'TenorSpread', leg1:'2600002.IB',  leg2:'260010.IB',   regime:'momentum',     dir:'BUY',  z:0.9729,  spread:49.02,  mean:38.8691,  vol:10.4339, hl:null,   cr:-36.5062, be:3.6506, stop:2.0035, target:1.0289, score:3.6536,  wt:0.197  },
  { id:'Repo7d-1y2y',type:'SwapSpread',  leg1:'FR007S2Y.IR', leg2:'FR007S1Y.IR', regime:'momentum',     dir:'BUY',  z:-0.451,  spread:0.375,  mean:4.0873,   vol:8.2308,  hl:null,   cr:-2.37,    be:1.185,  stop:0.9243, target:1.1327, score:3.5228,  wt:0.0152 },
  { id:'Repo7d-3y5y',type:'SwapSpread',  leg1:'FR007S5Y.IR', leg2:'FR007S3Y.IR', regime:'momentum',     dir:'BUY',  z:-0.897,  spread:6.375,  mean:13.2224,  vol:7.6337,  hl:null,   cr:-1.56,    be:0.312,  stop:1.0531, target:1.5254, score:3.1201,  wt:0.0152 },
  { id:'Basis-1y5y', type:'SwapSpread',  leg1:'',            leg2:'',            regime:'momentum',     dir:'SELL', z:-0.3169, spread:3.375,  mean:6.1411,   vol:8.7281,  hl:null,   cr:1.05,     be:null,   stop:1.78,   target:1.4979, score:3.0754,  wt:0.0152 },
  { id:'CDB-10s30s', type:'TenorSpread', leg1:'210221.IB',   leg2:'260205.IB',   regime:'momentum',     dir:'BUY',  z:1.5481,  spread:55.53,  mean:40.8426,  vol:9.4877,  hl:null,   cr:-28.8825, be:2.8883, stop:1.837,  target:0.4151, score:2.9122,  wt:0.5    },
  { id:'CDB-5s10s',  type:'TenorSpread', leg1:'260205.IB',   leg2:'260203.IB',   regime:'momentum',     dir:'BUY',  z:0.8933,  spread:22.25,  mean:17.992,   vol:4.7665,  hl:null,   cr:-10.5625, be:2.1125, stop:1.4771, target:0.8174, score:2.626,   wt:0.0152 },
  { id:'250016.IB',  type:'TBondCurve',  leg1:'250016.IB',   leg2:'240004.IB',   regime:'mean-reverting',dir:'BUY', z:1.9334,  spread:0.036,  mean:-0.0009,  vol:0.0191,  hl:2.8087, cr:-3.905,   be:null,   stop:null,   target:null,   score:2.626,   wt:0.0152 },
  { id:'250208.IB',  type:'CBondCurve',  leg1:'250208.IB',   leg2:'240203.IB',   regime:'mean-reverting',dir:'BUY', z:2.8104,  spread:0.021,  mean:-0.0429,  vol:0.0227,  hl:null,   cr:-5.405,   be:null,   stop:null,   target:null,   score:2.626,   wt:0.0152 },
  { id:'250355.IB',  type:'CBondCurve',  leg1:'250355.IB',   leg2:'250218.IB',   regime:'mean-reverting',dir:'BUY', z:1.9268,  spread:0.0103, mean:-0.0344,  vol:0.0232,  hl:6.0561, cr:-6.47,    be:null,   stop:null,   target:null,   score:2.626,   wt:0.0152 },
];

const CHART_DATA = [
  { id:'CDB-10s30s',  wt:49.4, rc:8.1 }, { id:'CGB-10s30s',  wt:19.7, rc:3.2 },
  { id:'CDBCGB-30y',  wt:1.52, rc:0.8 }, { id:'Repo7d-6m2Y', wt:1.52, rc:1.1 },
  { id:'Repo7d-9m4Y', wt:1.52, rc:0.9 }, { id:'Repo7d-9m2Y', wt:1.52, rc:1.0 },
  { id:'Repo7d-6m1y', wt:1.52, rc:0.7 }, { id:'Repo7d-1y2Y', wt:1.52, rc:1.2 },
  { id:'Repo7d-3y5y', wt:1.52, rc:0.8 }, { id:'Basis-1y5Y',  wt:1.52, rc:0.6 },
  { id:'CDB-5s10s',   wt:1.52, rc:0.5 }, { id:'250208.IB',   wt:1.52, rc:0.4 },
  { id:'260005.IB',   wt:1.52, rc:0.3 }, { id:'250011.IB',   wt:1.52, rc:0.2 },
  { id:'250016.IB',   wt:1.52, rc:0.2 },
];

const CANDIDATES = [
  { id:'CDB-10s30s',  type:'TenorSpread', regime:'MOM', dir:'BUY',  z:'+1.5σ', saved:false },
  { id:'Basis-1y5y',  type:'SwapSpread',  regime:'MOM', dir:'SELL', z:'-0.3σ', saved:false },
  { id:'CDB-5s10s',   type:'TenorSpread', regime:'MOM', dir:'BUY',  z:'+0.9σ', saved:false },
  { id:'Repo7d-3y5y', type:'SwapSpread',  regime:'MOM', dir:'BUY',  z:'-0.9σ', saved:false },
  { id:'Repo7d-9m4y', type:'SwapSpread',  regime:'MOM', dir:'BUY',  z:'-0.6σ', saved:false },
  { id:'CDBCGB-30y',  type:'TenorSpread', regime:'MOM', dir:'BUY',  z:'-0.9σ', saved:false },
];

const SAVED_POS = [
  { id:'TL-Cal',      type:'TermBasis',   regime:'MR',  dir:'BUY'  },
  { id:'Repo7d-6m1y', type:'SwapSpread',  regime:'MOM', dir:'BUY'  },
  { id:'CGB-10s30s',  type:'TenorSpread', regime:'MOM', dir:'BUY'  },
  { id:'Repo7d-1y2y', type:'SwapSpread',  regime:'MOM', dir:'BUY'  },
  { id:'T-FtSwp',     type:'FuturesSwap', regime:'MR',  dir:'BUY'  },
  { id:'Repo7d-6m2y', type:'SwapSpread',  regime:'MOM', dir:'BUY'  },
  { id:'260005-OTR',  type:'TBondCurve',  regime:'—',   dir:'—'    },
  { id:'250355-OTR',  type:'CBondCurve',  regime:'—',   dir:'—'    },
  { id:'250016-OTR',  type:'TBondCurve',  regime:'—',   dir:'—'    },
];

// Correlation matrix labels (lower triangle)
const CORR_LABELS = ['CDB-10s30s','Basis-1y5y','CDB-5s10s','Repo7d-3y5y','Repo7d-9m4y','CDBCGB-30y','Repo7d-6m1y','Repo7d-1y2y','CDBCGB-5y','220017-OTR'];
const CORR_VALS = {
  'Basis-1y5y,CDB-10s30s':0.22, 'CDB-5s10s,CDB-10s30s':0.71, 'CDB-5s10s,Basis-1y5y':0.18,
  'Repo7d-3y5y,CDB-10s30s':0.08,'Repo7d-3y5y,Basis-1y5y':0.31,'Repo7d-3y5y,CDB-5s10s':0.12,
  'Repo7d-9m4y,CDB-10s30s':0.06,'Repo7d-9m4y,Basis-1y5y':0.29,'Repo7d-9m4y,CDB-5s10s':0.10,'Repo7d-9m4y,Repo7d-3y5y':0.88,
  'CDBCGB-30y,CDB-10s30s':0.55, 'CDBCGB-30y,Basis-1y5y':0.14, 'CDBCGB-30y,CDB-5s10s':0.42,  'CDBCGB-30y,Repo7d-3y5y':0.04,  'CDBCGB-30y,Repo7d-9m4y':0.05,
  'Repo7d-6m1y,CDB-10s30s':0.04,'Repo7d-6m1y,Basis-1y5y':0.72,'Repo7d-6m1y,CDB-5s10s':0.09,  'Repo7d-6m1y,Repo7d-3y5y':0.61, 'Repo7d-6m1y,Repo7d-9m4y':0.58, 'Repo7d-6m1y,CDBCGB-30y':0.03,
  'Repo7d-1y2y,CDB-10s30s':0.03,'Repo7d-1y2y,Basis-1y5y':0.68,'Repo7d-1y2y,CDB-5s10s':0.08,  'Repo7d-1y2y,Repo7d-3y5y':0.55, 'Repo7d-1y2y,Repo7d-9m4y':0.51, 'Repo7d-1y2y,CDBCGB-30y':0.02, 'Repo7d-1y2y,Repo7d-6m1y':0.89,
  'CDBCGB-5y,CDB-10s30s':0.48,  'CDBCGB-5y,Basis-1y5y':0.11,  'CDBCGB-5y,CDB-5s10s':0.36,   'CDBCGB-5y,Repo7d-3y5y':0.03,   'CDBCGB-5y,Repo7d-9m4y':0.04,   'CDBCGB-5y,CDBCGB-30y':0.78,   'CDBCGB-5y,Repo7d-6m1y':0.02,   'CDBCGB-5y,Repo7d-1y2y':0.01,
  '220017-OTR,CDB-10s30s':0.39, '220017-OTR,Basis-1y5y':0.08,  '220017-OTR,CDB-5s10s':0.28,   '220017-OTR,Repo7d-3y5y':0.02,  '220017-OTR,Repo7d-9m4y':0.02,  '220017-OTR,CDBCGB-30y':0.61,  '220017-OTR,Repo7d-6m1y':0.01,  '220017-OTR,Repo7d-1y2y':0.01,  '220017-OTR,CDBCGB-5y':0.91,
};

function corrColor(v) {
  if (v === undefined) return 'transparent';
  if (v > 0) return `rgba(30,80,160,${v*0.85})`;
  return `rgba(200,60,40,${Math.abs(v)*0.85})`;
}

function AlphaPortfolio() {
  const { useState } = React;
  const accentAmber = 'var(--accent-amber)';
  const [open, setOpen] = useState({ corr: true, config: true, results: true });
  const [spreadType, setSpreadType] = useState('TBondCurve');
  const [instrument, setInstrument] = useState('210011.IB');
  const [capital, setCapital] = useState(10);
  const [dv01, setDv01] = useState(5);
  const [method, setMethod] = useState('Risk Parity');

  const toggle = k => setOpen(o => ({ ...o, [k]: !o[k] }));

  // shared header for collapsible cards
  function CardHeader({ title, id, badge, action }) {
    return (
      <div onClick={() => toggle(id)} style={{ display:'flex', alignItems:'center', justifyContent:'space-between',
        padding:'11px 16px', background:'var(--surface-panel)', borderBottom: open[id] ? '1px solid var(--border-strong)' : 'none',
        cursor:'pointer', userSelect:'none' }}>
        <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
          <span style={{ font:'var(--type-h2)', fontSize:'13px', fontWeight:600, color:'var(--text-primary)' }}>{title}</span>
          {badge && <span style={{ font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)',
            background:'var(--surface-input)', padding:'2px 7px', borderRadius:'3px', border:'1px solid var(--border-default)' }}>{badge}</span>}
        </div>
        <div style={{ display:'flex', alignItems:'center', gap:'12px' }}>
          {action}
          <span style={{ color:'var(--text-muted)', fontSize:'12px' }}>{open[id] ? '▲' : '▼'}</span>
        </div>
      </div>
    );
  }

  function DirBadge({ d }) {
    return <span style={{ padding:'1px 5px', borderRadius:'2px', fontSize:'8px', fontWeight:700,
      background:d==='BUY'?'rgba(52,211,153,0.15)':d==='SELL'?'rgba(239,68,68,0.15)':'rgba(255,255,255,0.06)',
      color:d==='BUY'?'#34d399':d==='SELL'?'#f87171':'var(--text-muted)' }}>{d}</span>;
  }

  function RegimeBadge({ r }) {
    return <span style={{ padding:'1px 5px', borderRadius:'2px', fontSize:'8px', fontWeight:600,
      background:r==='MOM'?'rgba(224,162,60,0.15)':r==='MR'?'rgba(34,211,238,0.12)':'rgba(255,255,255,0.06)',
      color:r==='MOM'?accentAmber:r==='MR'?'var(--accent-cyan)':'var(--text-muted)' }}>{r}</span>;
  }

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'10px' }}>
      <div>
        <h1 style={{ margin:'0 0 4px', font:'var(--type-h1)', color:'var(--text-primary)' }}>Alpha Book Portfolio</h1>
        <div style={{ font:'var(--type-meta)', color:'var(--text-muted)' }}>Instrument selection · portfolio configuration · optimised allocation</div>
      </div>

      {/* ── Card 1: Instrument Selection & Correlation ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <CardHeader title="Instrument Selection & Correlation" id="corr" badge="17 instruments · 52 days" />
        {open.corr && (
          <div style={{ padding:'14px 16px', display:'flex', flexDirection:'column', gap:'14px' }}>
            {/* Add trade row */}
            <div style={{ display:'flex', alignItems:'center', gap:'10px', flexWrap:'wrap' }}>
              <div style={{ display:'flex', flexDirection:'column', gap:'4px' }}>
                <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>Spread Type</div>
                <select value={spreadType} onChange={e=>setSpreadType(e.target.value)} style={{ padding:'6px 10px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', color:'var(--text-primary)', font:'var(--type-data)', fontSize:'11px', cursor:'pointer' }}>
                  {['TBondCurve','CBondCurve','SwapSpread','TenorSpread','FuturesSwap'].map(t=><option key={t}>{t}</option>)}
                </select>
              </div>
              <div style={{ display:'flex', flexDirection:'column', gap:'4px' }}>
                <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>Instrument</div>
                <select value={instrument} onChange={e=>setInstrument(e.target.value)} style={{ padding:'6px 10px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', color:'var(--text-primary)', font:'var(--type-data)', fontSize:'11px', cursor:'pointer' }}>
                  {['210011.IB','250016.IB','260005.IB','250022.IB'].map(t=><option key={t}>{t}</option>)}
                </select>
              </div>
              <div style={{ marginTop:'14px' }}>
                <button style={{ padding:'7px 14px', background:'var(--positive)', color:'var(--navy-950)', border:'none', borderRadius:'4px', font:'var(--type-label)', fontSize:'11px', fontWeight:700, cursor:'pointer' }}>+ Add Trade</button>
              </div>
            </div>

            {/* Candidate + Saved panels */}
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'12px' }}>
              <div>
                <div style={{ font:'var(--type-label)', fontSize:'10px', color:accentAmber, marginBottom:'8px', display:'flex', alignItems:'center', gap:'8px' }}>
                  <span style={{ width:'3px', height:'14px', background:accentAmber, borderRadius:'1px', display:'inline-block' }}></span>
                  Candidate Instruments <span style={{ color:'var(--text-muted)', fontWeight:400 }}>6 trades</span>
                </div>
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'6px' }}>
                  {CANDIDATES.map((c,i) => (
                    <div key={i} style={{ background:'var(--surface-raised)', border:'1px solid var(--border-strong)', borderRadius:'5px', padding:'8px 10px' }}>
                      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:'4px' }}>
                        <span style={{ font:'var(--type-data)', fontSize:'10px', color:'var(--text-primary)', fontWeight:600 }}>{c.id}</span>
                        <span style={{ font:'var(--type-meta)', fontSize:'8px', color:'var(--text-muted)', cursor:'pointer' }}>✕</span>
                      </div>
                      <div style={{ font:'var(--type-meta)', fontSize:'8px', color:'var(--text-muted)', marginBottom:'5px' }}>{c.type}</div>
                      <div style={{ display:'flex', gap:'3px', alignItems:'center' }}>
                        <RegimeBadge r={c.regime} />
                        <DirBadge d={c.dir} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <div style={{ font:'var(--type-label)', fontSize:'10px', color:'var(--accent-cyan)', marginBottom:'8px', display:'flex', alignItems:'center', gap:'8px' }}>
                  <span style={{ width:'3px', height:'14px', background:'var(--accent-cyan)', borderRadius:'1px', display:'inline-block' }}></span>
                  Saved Positions <span style={{ color:'var(--text-muted)', fontWeight:400 }}>16 trades · read-only</span>
                </div>
                <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'6px' }}>
                  {SAVED_POS.map((c,i) => (
                    <div key={i} style={{ background:'var(--surface-raised)', border:'1px solid var(--border-strong)', borderRadius:'5px', padding:'8px 10px' }}>
                      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', marginBottom:'4px' }}>
                        <span style={{ font:'var(--type-data)', fontSize:'10px', color:'var(--text-primary)', fontWeight:600 }}>{c.id}</span>
                        <span style={{ font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)' }}>{c.dir !== '—' ? '●' : '○'}</span>
                      </div>
                      <div style={{ font:'var(--type-meta)', fontSize:'8px', color:'var(--text-muted)', marginBottom:'5px' }}>{c.type}</div>
                      <div style={{ display:'flex', gap:'3px', alignItems:'center' }}>
                        {c.regime !== '—' && <RegimeBadge r={c.regime} />}
                        {c.dir !== '—' && <DirBadge d={c.dir} />}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Correlation matrix */}
            <div>
              <div style={{ font:'var(--type-label)', fontSize:'11px', color:'var(--text-secondary)', marginBottom:'8px' }}>Curated Correlation Matrix</div>
              <div style={{ overflowX:'auto', border:'1px solid var(--border-strong)', borderRadius:'6px' }}>
                <table style={{ borderCollapse:'collapse', font:'var(--type-data)', fontSize:'9px' }}>
                  <thead>
                    <tr>
                      <th style={{ padding:'6px 8px', minWidth:'80px', font:'var(--type-label)', fontSize:'8px', color:'var(--text-muted)' }}></th>
                      {CORR_LABELS.slice(0,-1).map(l => (
                        <th key={l} style={{ padding:'4px 6px', font:'var(--type-label)', fontSize:'7px', color:'var(--text-muted)',
                          writingMode:'vertical-rl', transform:'rotate(180deg)', whiteSpace:'nowrap', maxHeight:'70px' }}>{l}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {CORR_LABELS.slice(1).map((row, ri) => (
                      <tr key={row}>
                        <td style={{ padding:'4px 8px', font:'var(--type-label)', fontSize:'8px', color:'var(--text-muted)', whiteSpace:'nowrap', borderRight:'1px solid var(--border-strong)' }}>{row}</td>
                        {CORR_LABELS.slice(0, ri+1).map(col => {
                          const key1 = `${row},${col}`, key2 = `${col},${row}`;
                          const v = CORR_VALS[key1] ?? CORR_VALS[key2];
                          return (
                            <td key={col} style={{ padding:'4px 6px', textAlign:'center', background:corrColor(v),
                              color: v !== undefined ? 'rgba(255,255,255,0.85)' : 'transparent', fontSize:'8px', fontWeight:600, minWidth:'32px' }}>
                              {v !== undefined ? v.toFixed(2) : ''}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Legend */}
              <div style={{ display:'flex', alignItems:'center', gap:'8px', marginTop:'8px', font:'var(--type-meta)', fontSize:'8px', color:'var(--text-muted)' }}>
                <span>-1</span>
                <div style={{ flex:1, maxWidth:'120px', height:'5px', borderRadius:'3px', background:'linear-gradient(90deg,rgba(200,60,40,0.85),rgba(255,255,255,0.08),rgba(30,80,160,0.85))' }}></div>
                <span>+1</span>
              </div>
            </div>

            <div style={{ display:'flex', alignItems:'center', gap:'14px' }}>
              <button style={{ padding:'7px 16px', background:accentAmber, color:'var(--navy-950)', border:'none', borderRadius:'4px', font:'var(--type-label)', fontSize:'11px', fontWeight:700, cursor:'pointer' }}>
                ↻ Recalculate Correlation
              </button>
              <span style={{ font:'var(--type-meta)', fontSize:'10px', color:'var(--text-muted)' }}>✓ Recalculated at 07:30:30 (17 instruments, 52 days)</span>
            </div>
          </div>
        )}
      </div>

      {/* ── Card 2: Configuration ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <CardHeader title="Configuration" id="config" />
        {open.config && (
          <div style={{ padding:'14px 16px', display:'flex', flexWrap:'wrap', gap:'20px', alignItems:'flex-end' }}>
            {[
              { label:'Total Capital', value:capital, set:setCapital, unit:'Billion CNY', min:1, max:100 },
              { label:'Total Single Side DV01', value:dv01, set:setDv01, unit:'Million CNY', min:1, max:50 },
            ].map(({ label, value, set, unit, min, max }) => (
              <div key={label} style={{ display:'flex', flexDirection:'column', gap:'4px' }}>
                <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>{label}</div>
                <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                  <input type="number" value={value} min={min} max={max} onChange={e=>set(Number(e.target.value))}
                    style={{ width:'70px', padding:'6px 8px', background:'var(--surface-input)', border:'1px solid var(--border-default)',
                      borderRadius:'4px', color:'var(--text-primary)', font:'var(--type-data)', fontSize:'12px', fontWeight:600, textAlign:'right' }} />
                  <span style={{ font:'var(--type-meta)', fontSize:'10px', color:'var(--text-muted)' }}>{unit}</span>
                </div>
              </div>
            ))}
            <div style={{ display:'flex', flexDirection:'column', gap:'4px' }}>
              <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>Method</div>
              <div style={{ display:'flex', gap:'4px', background:'var(--surface-input)', padding:'3px', borderRadius:'5px', border:'1px solid var(--border-default)' }}>
                {['Risk Parity','Equal Weight','Max Sharpe'].map(m => (
                  <button key={m} onClick={()=>setMethod(m)} style={{ padding:'5px 12px', font:'var(--type-label)', fontSize:'10px', border:'none',
                    borderRadius:'3px', cursor:'pointer', transition:'all 0.15s',
                    background: method===m ? accentAmber : 'transparent',
                    color: method===m ? 'var(--navy-950)' : 'var(--text-muted)' }}>{m}</button>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Card 3: Portfolio Allocation Results ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <CardHeader title="Portfolio Allocation Results" id="results"
          action={
            <button onClick={e=>e.stopPropagation()} style={{ padding:'6px 16px', background:accentAmber, color:'var(--navy-950)',
              border:'none', borderRadius:'4px', font:'var(--type-label)', fontSize:'11px', fontWeight:700, cursor:'pointer', letterSpacing:'0.04em' }}>
              RUN OPTIMIZATION
            </button>
          }
        />
        {open.results && (
          <div style={{ display:'flex', flexDirection:'column' }}>
            {/* Stats bar */}
            <div style={{ padding:'10px 16px', background:'rgba(255,255,255,0.02)', borderBottom:'1px solid var(--border-strong)',
              display:'flex', flexWrap:'wrap', gap:'6px 28px', alignItems:'center' }}>
              {[['Total Trades','22'],['Capital Allocated','10.0 B CNY'],['DV01 Budget','5.0 MM CNY'],['Avg Score','3.354'],['Risk Parity','σ(RC)=0.188'],['BUY/SELL','21 / 1']].map(([k,v]) => (
                <span key={k} style={{ font:'var(--type-meta)', fontSize:'10px' }}>
                  <span style={{ color:'var(--text-muted)' }}>{k}: </span>
                  <span style={{ color:'var(--text-primary)', fontWeight:600 }}>{v}</span>
                </span>
              ))}
              <span style={{ font:'var(--type-meta)', fontSize:'10px', color:'var(--text-muted)', flexBasis:'100%' }}>
                By Regime: <span style={{ color:accentAmber }}>momentum: 7</span>{' | '}
                <span style={{ color:'var(--accent-cyan)' }}>mean-reverting: 3</span>{' | '}
                <span style={{ color:'var(--text-muted)' }}>other: 1</span>
              </span>
            </div>

            {/* Table */}
            <div style={{ overflowX:'auto' }}>
              <table style={{ width:'100%', borderCollapse:'collapse', font:'var(--type-data)', fontSize:'10px' }}>
                <thead>
                  <tr style={{ background:'var(--surface-panel)', borderBottom:'1px solid var(--border-strong)' }}>
                    {['$ID','$TYPE','$LEG 1','$LEG 2','$REGIME','$DIR','$Z','$SPREAD','$MEAN','$VOL','$HL(D)','$C+R(3M)','$B/E(3M)','$STOP','$TARGET','$SCORE','$WEIGHT'].map(h => (
                      <th key={h} style={{ padding:'6px 8px', textAlign:['$ID','$TYPE','$LEG 1','$LEG 2','$REGIME','$DIR'].includes(h)?'left':'right',
                        font:'var(--type-label)', fontSize:'8px', color:'var(--text-muted)', letterSpacing:'0.05em', whiteSpace:'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {STEP3_ROWS.map((r,i) => (
                    <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.04)', background:i%2===0?'transparent':'rgba(255,255,255,0.015)' }}>
                      <td style={{ padding:'4px 8px', color:'var(--text-primary)', fontWeight:600, whiteSpace:'nowrap' }}>{r.id}</td>
                      <td style={{ padding:'4px 8px', color:'var(--text-muted)' }}>{r.type}</td>
                      <td style={{ padding:'4px 8px', color:'var(--text-secondary)', fontSize:'9px' }}>{r.leg1||'—'}</td>
                      <td style={{ padding:'4px 8px', color:'var(--text-secondary)', fontSize:'9px' }}>{r.leg2||'—'}</td>
                      <td style={{ padding:'4px 8px' }}>
                        <span style={{ padding:'1px 5px', borderRadius:'2px', fontSize:'8px', fontWeight:600,
                          background:r.regime==='momentum'?'rgba(224,162,60,0.15)':'rgba(34,211,238,0.12)',
                          color:r.regime==='momentum'?accentAmber:'var(--accent-cyan)' }}>{r.regime}</span>
                      </td>
                      <td style={{ padding:'4px 8px' }}>
                        <span style={{ padding:'1px 6px', borderRadius:'2px', fontSize:'8px', fontWeight:700,
                          background:r.dir==='BUY'?'rgba(52,211,153,0.18)':'rgba(239,68,68,0.18)',
                          color:r.dir==='BUY'?'#34d399':'#f87171' }}>{r.dir}</span>
                      </td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:r.z>0?'#34d399':'#f87171', fontWeight:600 }}>{r.z.toFixed(4)}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:'var(--text-primary)' }}>{r.spread.toFixed(3)}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:'var(--text-secondary)' }}>{r.mean.toFixed(4)}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:'var(--text-secondary)' }}>{r.vol.toFixed(4)}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:'var(--text-muted)' }}>{r.hl!=null?r.hl.toFixed(4):'—'}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:r.cr>=0?'#34d399':'#f87171' }}>{r.cr.toFixed(4)}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:'var(--text-muted)' }}>{r.be!=null?r.be.toFixed(4):'—'}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:'#f87171' }}>{r.stop!=null?r.stop.toFixed(4):'—'}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:'#34d399' }}>{r.target!=null?r.target.toFixed(4):'—'}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:accentAmber, fontWeight:600 }}>{r.score.toFixed(4)}</td>
                      <td style={{ padding:'4px 8px', textAlign:'right', color:'var(--text-secondary)' }}>{r.wt.toFixed(4)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Chart */}
            <div style={{ padding:'16px', borderTop:'1px solid var(--border-strong)' }}>
              <div style={{ font:'var(--type-label)', color:'var(--text-secondary)', fontSize:'11px', marginBottom:'10px' }}>Portfolio Allocation: Weights vs Risk Contributions</div>
              <div style={{ display:'flex', gap:'16px', marginBottom:'12px' }}>
                {[[accentAmber,'Weight (%)'],['#34d399','Risk Contribution (%)']].map(([c,l]) => (
                  <div key={l} style={{ display:'flex', alignItems:'center', gap:'5px', font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)' }}>
                    <div style={{ width:'10px', height:'10px', background:c, borderRadius:'1px', opacity:0.8 }}></div>{l}
                  </div>
                ))}
              </div>
              <div style={{ display:'flex', alignItems:'flex-end', gap:'6px', overflowX:'auto', paddingBottom:'28px' }}>
                {CHART_DATA.map((d,i) => {
                  const maxWt = Math.max(...CHART_DATA.map(x=>x.wt));
                  return (
                    <div key={i} style={{ display:'flex', flexDirection:'column', alignItems:'center', gap:'2px', minWidth:'30px', flex:1 }}>
                      <div style={{ display:'flex', gap:'2px', alignItems:'flex-end', height:'80px' }}>
                        <div style={{ width:'11px', height:`${(d.wt/maxWt)*80}px`, background:accentAmber, borderRadius:'1px 1px 0 0', opacity:0.85 }}></div>
                        <div style={{ width:'11px', height:`${(d.rc/maxWt)*80}px`, background:'#34d399', borderRadius:'1px 1px 0 0', opacity:0.75 }}></div>
                      </div>
                      <div style={{ font:'var(--type-meta)', fontSize:'7px', color:'var(--text-muted)', writingMode:'vertical-rl',
                        transform:'rotate(180deg)', maxHeight:'56px', overflow:'hidden', whiteSpace:'nowrap' }}>{d.id}</div>
                    </div>
                  );
                })}
              </div>
              <div style={{ textAlign:'center', font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)' }}>Trade ID</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
window.AlphaPortfolio = AlphaPortfolio;
