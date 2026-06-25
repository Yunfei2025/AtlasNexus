// Beta Book > Portfolio — configuration + risk budgets + allocation results
const _ns_bport = window.AtlasNexusDesignSystem_988df3;

const ASSET_POOL = [
  { name:'Silver',   desc:'Precious Metals — N/A', color:'#f59e0b' },
  { name:'Gold',     desc:'Precious Metals — N/A', color:'#f59e0b' },
  { name:'USDCNY',   desc:'USD/CNY — Spot',         color:'#f59e0b' },
  { name:'CN2Y',     desc:'China Gov Bond — 2Y',    color:'#f59e0b' },
  { name:'CN5Y',     desc:'China Gov Bond — 5Y',    color:'#f59e0b' },
];

const RISK_FACTORS = [
  { name:'CMDL.AG',    vol:'57.36%', rpMax:1667, dv01:null, exposure:1667 },
  { name:'CMDL.AU',    vol:'26.39%', rpMax:1667, dv01:null, exposure:1667 },
  { name:'FXDL.USDCNY',vol:'2.38%',  rpMax:1667, dv01:null, exposure:1667 },
  { name:'IRCV.CN',    vol:'0.05%',  rpMax:1286, dv01:0.33, exposure:1286 },
  { name:'IRDL.CN',    vol:'0.12%',  rpMax:1903, dv01:1.38, exposure:1903 },
  { name:'IRSL.CN',    vol:'0.11%',  rpMax:1811, dv01:1.63, exposure:1811 },
];

function BetaPortfolio() {
  const { useState } = React;
  const [assetType, setAssetType] = useState('Rates');
  const [capital, setCapital] = useState('10');
  const [capUnit, setCapUnit] = useState('Billion');
  const [maxDur, setMaxDur] = useState('5');
  const [model, setModel] = useState('Deterministic');
  const [budgetMode, setBudgetMode] = useState('Risk Parity');
  const [hasResults, setHasResults] = useState(false);

  const accentBlue = 'var(--accent-blue)';

  const Radio = ({ value, checked, onChange, label }) => (
    <label style={{ display:'flex', alignItems:'center', gap:'5px', cursor:'pointer', font:'var(--type-label)', fontSize:'11px', color: checked ? 'var(--text-primary)' : 'var(--text-muted)' }}>
      <div onClick={onChange} style={{
        width:'12px', height:'12px', borderRadius:'50%', flexShrink:0,
        border:'2px solid '+(checked ? accentBlue : 'var(--border-strong)'),
        background: checked ? accentBlue : 'transparent', transition:'all 0.15s', cursor:'pointer',
      }}></div>
      <span onClick={onChange}>{label}</span>
    </label>
  );

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'14px' }}>

      {/* Configuration card */}
      <div style={{ background:'var(--surface-panel)', border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        {/* Config header bar */}
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'12px 18px', borderBottom:'1px solid var(--border-strong)', flexWrap:'wrap', gap:'12px' }}>
          <span style={{ font:'var(--type-h3)', color:'var(--text-primary)', fontSize:'13px' }}>Configuration</span>
          <div style={{ display:'flex', alignItems:'center', gap:'16px', flexWrap:'wrap' }}>
            <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
              <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'11px' }}>Total Capital:</span>
              <input value={capital} onChange={e=>setCapital(e.target.value)} style={{ width:'52px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 8px', font:'var(--type-data)', fontSize:'12px', color:'var(--text-primary)', textAlign:'right' }}/>
              <select value={capUnit} onChange={e=>setCapUnit(e.target.value)} style={{ appearance:'none', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 24px 5px 8px', font:'var(--type-data)', fontSize:'11px', color:'var(--text-primary)', cursor:'pointer' }}>
                {['Billion','Million'].map(u=><option key={u}>{u}</option>)}
              </select>
              <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'11px' }}>CNY</span>
            </div>
            <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
              <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'11px' }}>Max Dur:</span>
              <input value={maxDur} onChange={e=>setMaxDur(e.target.value)} style={{ width:'40px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 8px', font:'var(--type-data)', fontSize:'12px', color:'var(--text-primary)', textAlign:'right' }}/>
              <span style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'10px' }}>→ max DV01 {(parseFloat(maxDur)||0).toFixed(1)} MM</span>
            </div>
            <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
              <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'11px' }}>Model:</span>
              <div style={{ background:'var(--surface-input)', border:`1px solid ${accentBlue}`, borderRadius:'4px', padding:'4px 10px', font:'var(--type-label)', fontSize:'11px', color: accentBlue, cursor:'pointer' }}>{model}</div>
            </div>
          </div>
        </div>

        {/* Two-column body */}
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'0' }}>

          {/* LEFT — Asset Selection */}
          <div style={{ padding:'16px 18px', borderRight:'1px solid var(--border-strong)' }}>
            <div style={{ font:'var(--type-h3)', color:'var(--text-primary)', fontSize:'13px', marginBottom:'12px' }}>Asset Selection</div>
            <div style={{ display:'flex', alignItems:'center', gap:'16px', marginBottom:'14px' }}>
              <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'11px' }}>Type:</span>
              <Radio value="Rates" checked={assetType==='Rates'} onChange={()=>setAssetType('Rates')} label="Rates" />
              <Radio value="Cmdty" checked={assetType==='Cmdty'} onChange={()=>setAssetType('Cmdty')} label="Cmdty" />
            </div>
            <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'8px' }}>
              <span style={{ font:'var(--type-label)', color:'var(--text-primary)', fontSize:'12px' }}>Asset Pool <span style={{ color:'var(--text-muted)' }}>({ASSET_POOL.length})</span></span>
              <button style={{ padding:'3px 10px', font:'var(--type-label)', fontSize:'10px', background:'rgba(239,68,68,0.15)', color:'#f87171', border:'1px solid rgba(239,68,68,0.3)', borderRadius:'4px', cursor:'pointer' }}>Clear</button>
            </div>
            <div style={{ display:'flex', flexDirection:'column', gap:'4px' }}>
              {ASSET_POOL.map((a,i) => (
                <div key={i} style={{ display:'flex', justifyContent:'space-between', alignItems:'center', padding:'7px 12px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'5px' }}>
                  <span style={{ font:'var(--type-data)', fontSize:'12px', color: a.color, fontWeight:600 }}>{a.name}</span>
                  <span style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'10px' }}>{a.desc}</span>
                </div>
              ))}
            </div>
          </div>

          {/* RIGHT — Risk Budgets */}
          <div style={{ padding:'16px 18px' }}>
            <div style={{ display:'flex', alignItems:'baseline', gap:'10px', marginBottom:'12px', flexWrap:'wrap' }}>
              <span style={{ font:'var(--type-h3)', color:'var(--text-primary)', fontSize:'13px' }}>Risk Budgets (Vol.∕ Risk Parity)</span>
              <span style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'9px' }}>Vol from 1Y EWMA · Budget = vol^0.5 · Level &gt; Slope &gt; Curvature · Floor 3%, Cap 25%</span>
            </div>
            {/* Mode radios */}
            <div style={{ display:'flex', gap:'18px', marginBottom:'12px' }}>
              {['Risk Parity','Factor Model Scaling','User Defined'].map(m => (
                <Radio key={m} value={m} checked={budgetMode===m} onChange={()=>setBudgetMode(m)} label={m} />
              ))}
              <span style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'10px', marginLeft:'4px' }}>RP Max = inv-vol weights · same result on every run</span>
            </div>
            {/* Table */}
            <table style={{ width:'100%', borderCollapse:'collapse', font:'var(--type-data)', fontSize:'11px' }}>
              <thead>
                <tr style={{ borderBottom:'1px solid var(--border-strong)' }}>
                  {['Factor','Vol %ann','RP Max (MM CNY)','DV01 (MM/bp)','Exposure (MM CNY)'].map(h=>(
                    <th key={h} style={{ padding:'5px 10px 5px 0', textAlign: h==='Factor'?'left':'right', font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', letterSpacing:'0.05em', whiteSpace:'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {RISK_FACTORS.map((r,i)=>(
                  <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.04)' }}>
                    <td style={{ padding:'6px 10px 6px 0', color: accentBlue, fontWeight:600 }}>{r.name}</td>
                    <td style={{ padding:'6px 0', textAlign:'right', color:'var(--text-secondary)' }}>{r.vol}</td>
                    <td style={{ padding:'6px 0', textAlign:'right', color:'var(--text-primary)' }}>{r.rpMax}</td>
                    <td style={{ padding:'6px 0', textAlign:'right', color: r.dv01?'var(--text-secondary)':'var(--text-muted)' }}>{r.dv01??'—'}</td>
                    <td style={{ padding:'6px 0', textAlign:'right', color:'var(--text-muted)' }}>{r.exposure}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'9px', marginTop:'10px', textAlign:'right' }}>
              Vol auto-refreshes from 1Y EWMA factor history. Run analysis to refresh RP Max from portfolio decomposition.
            </div>
          </div>
        </div>
      </div>

      {/* Portfolio Allocation Results */}
      <div style={{ background:'var(--surface-panel)', border:'1px solid var(--border-strong)', borderRadius:'8px', padding:'16px 18px' }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', marginBottom:'12px' }}>
          <span style={{ font:'var(--type-h3)', color:'var(--text-primary)', fontSize:'13px' }}>Portfolio Allocation Results</span>
          <button onClick={()=>setHasResults(true)} style={{
            padding:'7px 18px', font:'var(--type-label)', fontSize:'11px', fontWeight:700, letterSpacing:'0.06em',
            background: accentBlue, color:'#fff', border:'none', borderRadius:'5px', cursor:'pointer', transition:'filter 0.15s',
          }}
          onMouseEnter={e=>e.target.style.filter='brightness(1.15)'}
          onMouseLeave={e=>e.target.style.filter='brightness(1)'}
          >RUN ANALYSIS</button>
        </div>
        {!hasResults
          ? <div style={{ font:'var(--type-body)', color:'var(--text-muted)', fontSize:'12px' }}>No data available. Click 'Run Analysis' to start.</div>
          : <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(120px,1fr))', gap:'10px' }}>
              {RISK_FACTORS.map((r,i)=>(
                <div key={i} style={{ background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'5px', padding:'10px 12px' }}>
                  <div style={{ font:'var(--type-label)', color: accentBlue, fontWeight:700, marginBottom:'3px', fontSize:'12px' }}>{r.name}</div>
                  <div style={{ font:'var(--type-data)', color:'var(--text-primary)', fontSize:'14px', fontWeight:600 }}>{r.rpMax} MM</div>
                  <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'9px', marginTop:'2px' }}>{r.vol} vol</div>
                </div>
              ))}
            </div>
        }
      </div>

      {/* IRDL Hedge Overlay footer */}
      <div style={{ display:'flex', alignItems:'center', gap:'8px', font:'var(--type-meta)', fontSize:'11px' }}>
        <span style={{ fontSize:'14px' }}>🛡</span>
        <span style={{ color: accentBlue, fontWeight:600 }}>IRDL</span>
        <span style={{ color:'var(--accent-amber)', fontWeight:600 }}>Hedge</span>
        <span style={{ color:'var(--text-primary)', fontWeight:600 }}>Overlay</span>
        <span style={{ color:'var(--text-muted)' }}>· optional post-optimisation duration hedge via bond futures or pay-fixed IRS</span>
      </div>
    </div>
  );
}
window.BetaPortfolio = BetaPortfolio;
