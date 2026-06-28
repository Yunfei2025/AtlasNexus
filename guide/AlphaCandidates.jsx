// Alpha Book > Candidates — redesigned to match Portfolio card style + correlation heatmap
const _ns_ac = window.AtlasNexusDesignSystem_988df3;

const CORR_INSTRUMENTS = [
  'CDBCGB-5y','Repo7d-9m4y','Repo7d-6m1y','Repo7d-1y2y',
  'Shi3M-1y4y','CGB-5s10s','CDB-10s30s','CDBCGB-30y','Repo7d-3y5y','250011-OTR'
];

// Synthetic correlation values (lower triangle, range -1 to 1)
const RAW_CORR = {
  'Repo7d-9m4y,CDBCGB-5y':   0.12,
  'Repo7d-6m1y,CDBCGB-5y':   0.08, 'Repo7d-6m1y,Repo7d-9m4y':  0.77,
  'Repo7d-1y2y,CDBCGB-5y':   0.05, 'Repo7d-1y2y,Repo7d-9m4y':  0.68, 'Repo7d-1y2y,Repo7d-6m1y':  0.89,
  'Shi3M-1y4y,CDBCGB-5y':    0.03, 'Shi3M-1y4y,Repo7d-9m4y':   0.31, 'Shi3M-1y4y,Repo7d-6m1y':   0.28, 'Shi3M-1y4y,Repo7d-1y2y':   0.24,
  'CGB-5s10s,CDBCGB-5y':     0.41, 'CGB-5s10s,Repo7d-9m4y':    0.09, 'CGB-5s10s,Repo7d-6m1y':    0.07, 'CGB-5s10s,Repo7d-1y2y':    0.06, 'CGB-5s10s,Shi3M-1y4y':    0.02,
  'CDB-10s30s,CDBCGB-5y':    0.55, 'CDB-10s30s,Repo7d-9m4y':   0.06, 'CDB-10s30s,Repo7d-6m1y':   0.04, 'CDB-10s30s,Repo7d-1y2y':   0.03, 'CDB-10s30s,Shi3M-1y4y':   0.01, 'CDB-10s30s,CGB-5s10s':    0.71,
  'CDBCGB-30y,CDBCGB-5y':    0.78, 'CDBCGB-30y,Repo7d-9m4y':   0.04, 'CDBCGB-30y,Repo7d-6m1y':   0.03, 'CDBCGB-30y,Repo7d-1y2y':   0.02, 'CDBCGB-30y,Shi3M-1y4y':   0.01, 'CDBCGB-30y,CGB-5s10s':    0.42, 'CDBCGB-30y,CDB-10s30s':   0.55,
  'Repo7d-3y5y,CDBCGB-5y':   0.04, 'Repo7d-3y5y,Repo7d-9m4y':  0.88, 'Repo7d-3y5y,Repo7d-6m1y':  0.61, 'Repo7d-3y5y,Repo7d-1y2y':  0.55, 'Repo7d-3y5y,Shi3M-1y4y':  0.19, 'Repo7d-3y5y,CGB-5s10s':   0.05, 'Repo7d-3y5y,CDB-10s30s':  0.08, 'Repo7d-3y5y,CDBCGB-30y':  0.03,
  '250011-OTR,CDBCGB-5y':    0.91, '250011-OTR,Repo7d-9m4y':   0.02, '250011-OTR,Repo7d-6m1y':   0.01, '250011-OTR,Repo7d-1y2y':   0.01, '250011-OTR,Shi3M-1y4y':   0.01, '250011-OTR,CGB-5s10s':    0.28, '250011-OTR,CDB-10s30s':   0.39, '250011-OTR,CDBCGB-30y':   0.61, '250011-OTR,Repo7d-3y5y':  0.02,
};

function getCorr(a, b) {
  return RAW_CORR[`${a},${b}`] ?? RAW_CORR[`${b},${a}`] ?? null;
}

function corrCell(v, maxCorr) {
  if (v === null) return { bg: 'transparent', color: 'transparent', flagged: false };
  const flagged = Math.abs(v) > maxCorr;
  let bg;
  if (v > 0) bg = `rgba(30,80,160,${Math.min(v,1)*0.9})`;
  else        bg = `rgba(200,60,40,${Math.min(-v,1)*0.9})`;
  return { bg, color: 'rgba(255,255,255,0.85)', flagged };
}

const CANDIDATES_LIST = [
  { dir:'BUY',  name:'Repo7d-9m2y',  z:-0.4 },
  { dir:'SELL', name:'Basis-5y',     z:-0.9 },
  { dir:'BUY',  name:'250011-OTR',   z:+2.5 },
  { dir:'BUY',  name:'220017-OTR',   z:+2.0 },
  { dir:'BUY',  name:'250022-OTR',   z:+2.2 },
];

const MR_ROWS = [
  ['BUY','Repo7d-6m9m',1.1],['BUY','Repo7d-6m1y',1.0],['BUY','Repo7d-1y2y',0.3],
  ['BUY','Repo7d-2y5y',0.0],['BUY','Shi3M-1y4y',0.7], ['BUY','Shi3M-1y3y',0.5],
  ['BUY','Repo7d-9m2y',0.5],['BUY','Shi3M-6m3y',0.8], ['SELL','Shi3M-9m4y',-1.0],
];
const MOM_ROWS = [['BUY','CDBCGB-30y',-0.9],['BUY','CDBCGB-10y',-1.5]];
const UNC_ROWS = [
  ['BUY','CDB-10s30s',1.6],['BUY','210017-OTR',2.6],['BUY','CGB-5s10s',1.0],
  ['BUY','CDB-5s10s',0.6], ['BUY','CDBCGB-5y',-1.0],['BUY','CGB-10s30s',1.0],
];

function AlphaCandidates() {
  const { useState } = React;
  const { Checkbox, Slider, Input } = _ns_ac;
  const amber = 'var(--accent-amber)';
  const cyan  = 'var(--accent-cyan)';

  // filter state
  const [cats, setCats] = useState({
    'Bond-Curve':true,'Bond-Swap':true,'Swap Spreads':true,'Tenor Spreads':true,
    'Bond-Futures':false,'Calendar Spreads':false,'Futures-Swap':false,
  });
  const [z, setZ] = useState(2.0);
  const [dir, setDir] = useState('All');

  // corr state
  const [lookback, setLookback] = useState('1 Year');
  const [maxCorr, setMaxCorr] = useState(0.5);
  const [corrChecked, setCorrChecked] = useState(true);

  // card open state
  const [open, setOpen] = useState({ filters:true, candidates:true });
  const toggle = k => setOpen(o => ({...o, [k]:!o[k]}));
  const toggleCat = k => setCats(c => ({...c, [k]:!c[k]}));

  function CardHeader({ title, id, badge, action }) {
    return (
      <div onClick={() => toggle(id)} style={{ display:'flex', alignItems:'center', justifyContent:'space-between',
        padding:'11px 16px', background:'var(--surface-panel)',
        borderBottom: open[id] ? '1px solid var(--border-strong)' : 'none',
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
    return <span style={{ padding:'2px 7px', borderRadius:'3px', fontSize:'9px', fontWeight:700,
      background: d==='BUY'?'rgba(52,211,153,0.2)':'rgba(239,68,68,0.2)',
      color: d==='BUY'?'#34d399':'#f87171', letterSpacing:'0.04em' }}>{d}</span>;
  }

  // Z-score bar — matches screenshot style
  function ZBar({ z, maxZ=3 }) {
    const pct = Math.min(Math.abs(z)/maxZ, 1);
    const pos = z >= 0;
    const color = pos ? '#34d399' : '#f87171';
    return (
      <div style={{ display:'flex', alignItems:'center', gap:'8px', flex:1 }}>
        <div style={{ flex:1, height:'4px', background:'var(--surface-input)', borderRadius:'2px', position:'relative' }}>
          <div style={{ position:'absolute', top:0, bottom:0, left:'50%', width:`${pct*50}%`,
            marginLeft: pos ? 0 : `-${pct*50}%`,
            background: color, borderRadius:'2px', opacity:0.8 }}></div>
          <div style={{ position:'absolute', top:'-3px', bottom:'-3px', left:'50%', width:'1px', background:'rgba(255,255,255,0.2)' }}></div>
        </div>
        <span style={{ font:'var(--type-data)', fontSize:'11px', fontWeight:700, color, minWidth:'36px', textAlign:'right' }}>
          {z>=0?'+':''}{z.toFixed(1)}σ
        </span>
      </div>
    );
  }

  // Signal cluster
  function Cluster({ color, title, count, note, rows, cols=3 }) {
    return (
      <div>
        <div style={{ display:'flex', alignItems:'center', gap:'10px', marginBottom:'8px' }}>
          <span style={{ width:'4px', height:'16px', background:color, borderRadius:'1px', flexShrink:0 }}></span>
          <span style={{ font:'var(--type-label)', fontSize:'11px', color:'var(--text-primary)', fontWeight:600 }}>{title}</span>
          <span style={{ font:'var(--type-meta)', fontSize:'10px', color:'var(--text-muted)' }}>{count} signals</span>
        </div>
        {note && <div style={{ font:'var(--type-meta)', fontStyle:'italic', color:'var(--text-faint)', marginBottom:'8px', fontSize:'10px' }}>{note}</div>}
        <div style={{ display:'grid', gridTemplateColumns:`repeat(${cols},1fr)`, gap:'4px 20px' }}>
          {rows.map(([d,n,s],i) => (
            <div key={i} style={{ display:'flex', alignItems:'center', gap:'6px', padding:'3px 0' }}>
              <DirBadge d={d}/>
              <span style={{ font:'var(--type-data)', fontSize:'10px', color:'var(--text-secondary)', flex:1, minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{n}</span>
              <span style={{ font:'var(--type-data)', fontSize:'10px', fontWeight:600,
                color:s>=0?'#34d399':'#f87171', minWidth:'32px', textAlign:'right' }}>{s>=0?'+':''}{s.toFixed(1)}σ</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  // Corr heatmap with gradient legend (right side)
  function CorrHeatmap() {
    const N = CORR_INSTRUMENTS.length;
    // column headers = all except last; rows = all except first
    const cols = CORR_INSTRUMENTS.slice(0, N-1);
    const rows = CORR_INSTRUMENTS.slice(1);
    return (
      <div style={{ display:'flex', gap:'12px', alignItems:'flex-start' }}>
        <div style={{ overflowX:'auto', flex:1 }}>
          <table style={{ borderCollapse:'collapse', fontSize:'9px', width:'auto' }}>
            <thead>
              <tr>
                <td style={{ minWidth:'90px' }}></td>
                {cols.map(c => (
                  <th key={c} style={{ padding:'2px 3px', writingMode:'vertical-rl', transform:'rotate(180deg)',
                    whiteSpace:'nowrap', font:'var(--type-label)', fontSize:'7px', color:'var(--text-muted)',
                    maxHeight:'72px', verticalAlign:'bottom', textAlign:'left' }}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, ri) => (
                <tr key={row}>
                  <td style={{ padding:'2px 6px 2px 0', font:'var(--type-label)', fontSize:'7px', color:'var(--text-muted)',
                    whiteSpace:'nowrap', borderRight:'1px solid var(--border-strong)', textAlign:'right' }}>{row}</td>
                  {cols.slice(0, ri+1).map(col => {
                    const v = getCorr(row, col);
                    const { bg, color, flagged } = corrCell(v, maxCorr);
                    return (
                      <td key={col} style={{ padding:'2px', minWidth:'28px', height:'24px', background:bg,
                        textAlign:'center', fontSize:'8px', fontWeight:600, color,
                        outline: flagged ? '1.5px solid rgba(239,68,68,0.7)' : 'none',
                        outlineOffset:'-1.5px' }}>
                        {v !== null ? v.toFixed(2) : ''}
                      </td>
                    );
                  })}

                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Gradient legend */}
        <div style={{ display:'flex', flexDirection:'column', alignItems:'center', gap:'4px', flexShrink:0, paddingTop:'80px' }}>
          <span style={{ font:'var(--type-meta)', fontSize:'8px', color:'var(--text-muted)' }}>1</span>
          <div style={{ width:'14px', height:'120px', borderRadius:'3px',
            background:'linear-gradient(to bottom, rgba(30,80,160,0.95) 0%, rgba(255,255,255,0.08) 50%, rgba(200,60,40,0.95) 100%)' }}></div>
          <span style={{ font:'var(--type-meta)', fontSize:'8px', color:'var(--text-muted)' }}>0.5</span>
          <span style={{ font:'var(--type-meta)', fontSize:'8px', color:'var(--text-muted)', marginTop:'36px' }}>0</span>
          <span style={{ font:'var(--type-meta)', fontSize:'8px', color:'var(--text-muted)', marginTop:'36px' }}>-0.5</span>
          <span style={{ font:'var(--type-meta)', fontSize:'8px', color:'var(--text-muted)', marginTop:'4px' }}>-1</span>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'10px' }}>
      <div>
        <h1 style={{ margin:'0 0 3px', font:'var(--type-h1)', color:'var(--text-primary)' }}>Alpha Candidates Scanner</h1>
        <div style={{ font:'var(--type-meta)', color:'var(--text-muted)' }}>Scan for relative value opportunities · filter by z-score · check correlation before sizing</div>
      </div>

      {/* ── Card 1: Filters ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <CardHeader title="Filters" id="filters" badge="Spread Categories · Direction · Z-Score"
          action={
            <button onClick={e=>{e.stopPropagation();}} style={{ padding:'5px 14px', background:amber, color:'var(--navy-950)',
              border:'none', borderRadius:'4px', font:'var(--type-label)', fontSize:'10px', fontWeight:700, cursor:'pointer' }}>
              🔍 Scan Candidates
            </button>
          }
        />
        {open.filters && (
          <div style={{ padding:'14px 16px', display:'grid', gridTemplateColumns:'1fr 1fr', gap:'14px' }}>
            {/* Spread Categories */}
            <div style={{ background:'var(--surface-raised)', border:'1px solid var(--border-strong)', borderRadius:'6px', padding:'12px 14px' }}>
              <div style={{ font:'var(--type-label)', fontSize:'11px', color:'var(--text-secondary)', fontWeight:600, marginBottom:'10px' }}>Spread Categories</div>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'6px 16px' }}>
                {Object.keys(cats).map(k => <Checkbox key={k} label={k} checked={cats[k]} onChange={() => toggleCat(k)} />)}
              </div>
            </div>

            {/* Direction + Z-Score side by side */}
            <div style={{ background:'var(--surface-raised)', border:'1px solid var(--border-strong)', borderRadius:'6px', padding:'12px 14px',
              display:'grid', gridTemplateColumns:'auto 1fr', gap:'0 20px' }}>
              <div>
                <div style={{ font:'var(--type-label)', fontSize:'10px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:'8px' }}>Direction</div>
                <div style={{ display:'flex', flexDirection:'column', gap:'6px' }}>
                  {['All','BUY','SELL'].map(d => (
                    <label key={d} style={{ display:'flex', alignItems:'center', gap:'7px', cursor:'pointer',
                      font:'var(--type-sm)', fontSize:'11px', color: dir===d?'var(--text-primary)':'var(--text-secondary)' }}>
                      <input type="radio" checked={dir===d} onChange={()=>setDir(d)} style={{ accentColor:amber }}/>{d}
                    </label>
                  ))}
                </div>
              </div>
              <div>
                <div style={{ font:'var(--type-label)', fontSize:'10px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:'8px' }}>Z-Score Threshold (MR candidates)</div>
                <div style={{ display:'flex', alignItems:'center', gap:'8px', marginBottom:'8px' }}>
                  <span style={{ font:'var(--type-data)', fontSize:'22px', fontWeight:700, color:amber }}>{z.toFixed(1)}</span>
                  <span style={{ font:'var(--type-meta)', fontSize:'10px', color:'var(--text-muted)' }}>σ minimum</span>
                </div>
                <Slider min={1} max={3.5} step={0.1} value={z} onChange={setZ} />
                <div style={{ display:'flex', justifyContent:'space-between', font:'var(--type-meta)', color:'var(--text-muted)', marginTop:'5px', fontSize:'8px' }}>
                  {['1.0','1.5','2.0','2.5','3.0','3.5'].map(t => <span key={t}>{t}</span>)}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Cards 2+3: Candidates (left) + Correlation Check (right) ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <CardHeader title="Candidates & Correlation Check" id="candidates" badge="27 signals · 10:54:03"
          action={
            <button onClick={e=>{e.stopPropagation(); setCorrChecked(true);}} style={{
              padding:'5px 14px', background:corrChecked?'rgba(224,162,60,0.15)':amber,
              color: corrChecked?amber:'var(--navy-950)',
              border:`1px solid ${amber}`, borderRadius:'4px', font:'var(--type-label)',
              fontSize:'10px', fontWeight:700, cursor:'pointer' }}>
              {corrChecked ? '✓ Corr Checked' : '📊 Check Correlation'}
            </button>
          }
        />
        {open.candidates && (
          <div style={{ display:'flex', gap:'0', alignItems:'flex-start' }}>
            {/* Left: Candidates signals */}
            <div style={{ flex:1, minWidth:0, padding:'14px 16px', display:'flex', flexDirection:'column', gap:'18px',
              borderRight:'1px solid var(--border-strong)' }}>
              <div style={{ font:'var(--type-meta)', fontSize:'10px', color:'var(--text-muted)' }}>
                Regime: <span style={{ color:'var(--text-secondary)' }}>uncertain: 16</span>{' · '}
                <span style={{ color:'#34d399' }}>mean-reverting: 9</span>{' · '}
                <span style={{ color:amber }}>trending: 2</span>
              </div>
              <Cluster color="#34d399"           title="Mean-Reversion"   count={9}  rows={MR_ROWS} />
              <Cluster color={amber}             title="Momentum / Carry" count={2}  rows={MOM_ROWS} />
              <Cluster color="var(--text-muted)" title="Uncertain"        count={16}
                note="Regime unresolved — check spread chart before trading." rows={UNC_ROWS} />

              {/* Selected candidates for correlation check */}
              <div style={{ marginTop:'8px', paddingTop:'14px', borderTop:'1px solid var(--border-strong)' }}>
                <div style={{ font:'var(--type-label)', fontSize:'10px', color:amber, marginBottom:'8px', display:'flex', alignItems:'center', gap:'8px' }}>
                  <span style={{ width:'3px', height:'14px', background:amber, borderRadius:'1px', display:'inline-block' }}></span>
                  Selected for Correlation Check
                </div>
                <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:'4px 20px' }}>
                  {CANDIDATES_LIST.map((c,i) => (
                    <div key={i} style={{ display:'flex', alignItems:'center', gap:'5px', padding:'3px 0' }}>
                      <DirBadge d={c.dir}/>
                      <span style={{ font:'var(--type-data)', fontSize:'10px', color:'var(--text-secondary)', flex:1, minWidth:0, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>{c.name}</span>
                      <span style={{ font:'var(--type-data)', fontSize:'10px', fontWeight:600,
                        color:c.z>=0?'#34d399':'#f87171', minWidth:'32px', textAlign:'right' }}>{c.z>=0?'+':''}{c.z.toFixed(1)}σ</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Right: Correlation Check — natural width */}
            <div style={{ flexShrink:0, display:'flex', flexDirection:'column' }}>
              {/* Controls */}
              <div style={{ padding:'10px 14px', background:'rgba(255,255,255,0.02)', borderBottom:'1px solid var(--border-strong)' }}>
                <div style={{ font:'var(--type-meta)', fontSize:'10px', color:'var(--text-muted)', marginBottom:'8px' }}>
                  Verify low correlation before sizing.
                </div>
                <div style={{ display:'flex', alignItems:'center', gap:'10px', flexWrap:'wrap' }}>
                  <div style={{ display:'flex', alignItems:'center', gap:'6px' }}>
                    <span style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', whiteSpace:'nowrap' }}>Lookback:</span>
                    <select value={lookback} onChange={e=>setLookback(e.target.value)}
                      style={{ padding:'4px 7px', background:'var(--surface-input)', border:'1px solid var(--border-default)',
                        borderRadius:'4px', color:'var(--text-primary)', font:'var(--type-data)', fontSize:'10px', cursor:'pointer' }}>
                      {['3 Months','6 Months','1 Year','2 Years'].map(o=><option key={o}>{o}</option>)}
                    </select>
                  </div>
                  <div style={{ display:'flex', alignItems:'center', gap:'6px' }}>
                    <span style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', whiteSpace:'nowrap' }}>Max |Corr|:</span>
                    <select value={maxCorr} onChange={e=>setMaxCorr(+e.target.value)}
                      style={{ padding:'4px 7px', background:'var(--surface-input)', border:'1px solid var(--border-default)',
                        borderRadius:'4px', color:'var(--text-primary)', font:'var(--type-data)', fontSize:'10px', cursor:'pointer' }}>
                      {[0.3,0.4,0.5,0.6,0.7].map(o=><option key={o} value={o}>{o}</option>)}
                    </select>
                  </div>
                </div>
              </div>

              {/* Candidate chips */}
              <div style={{ padding:'6px 12px', borderBottom:'1px solid var(--border-strong)', display:'flex', gap:'4px', fontSize:'9px', color:'var(--text-muted)' }}>
                <span>{CANDIDATES_LIST.length} selected</span>
              </div>

              {/* Matrix title */}
              <div style={{ padding:'8px 14px 2px', font:'var(--type-label)', fontSize:'9px', color:'var(--text-secondary)' }}>
                Spread Correlation Matrix — {CORR_INSTRUMENTS.length} instruments (max |corr| ≤ {maxCorr})
              </div>

              {/* Heatmap */}
              <div style={{ padding:'6px 14px 14px' }}>
                <CorrHeatmap />
              </div>

              {/* Warning */}
              {maxCorr < 0.9 && (
                <div style={{ padding:'6px 14px', borderTop:'1px solid var(--border-strong)', font:'var(--type-meta)', fontSize:'9px',
                  color:'#f87171', background:'rgba(239,68,68,0.06)' }}>
                  ⚠ Red-outlined cells exceed max |corr| {maxCorr}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
window.AlphaCandidates = AlphaCandidates;
