// Alpha Book > Volatility — consistent with Candidates/Portfolio pattern
const _ns_av = window.AtlasNexusDesignSystem_988df3;

const TICKERS = ['AU.SHF','CU.SHF','RB.SHF','IC.CFE','IF.CFE','IH.CFE','T.CFE','TL.CFE'];
const KPI_DATA = { ticker:'AU.SHF', iv1m:23.68, iv2m:22.82, iv3m:23.39, signal:'Neutral',
  totalReturn:217.43, annReturn:127.04, volatility:47.91, sharpe:1.92, winRate:60.00, maxDD:-8.31, trades:50 };

// Generate synthetic time-series data
function genSeries(n, base, amp, trend=0) {
  const pts = [];
  let v = base;
  for (let i=0;i<n;i++) { v += (Math.random()-0.5)*amp + trend; pts.push(Math.max(base*0.4, v)); }
  return pts;
}
const N = 80;
const dates = Array.from({length:N},(_,i)=>{const d=new Date('2025-01-01');d.setDate(d.getDate()+Math.round(i*(540/N)));return d.toLocaleDateString('en',{month:'short',year:'2-digit'});});
const IV1M = genSeries(N,18,3,0.02);
const IV2M = IV1M.map(v=>v*0.97+Math.random()*1.5);
const IV3M = IV1M.map(v=>v*0.95+Math.random()*1.8);
const MID  = IV1M.map(v=>v);
const UPPER= MID.map(v=>v+6+Math.random()*2);
const LOWER= MID.map(v=>Math.max(5,v-6-Math.random()*2));
const CUM  = genSeries(N,1,0.05,0.015);
const ZSLOPE=Array.from({length:N},()=>(Math.random()-0.5)*4);

// Regime history
const REGIME_HISTORY=[
  {period:'Jan–Mar 2025',regime:'LOW VOL',  rv:14.2,iv:18.8,premium:4.6},
  {period:'Apr–Jun 2025',regime:'TRANSITION',rv:16.8,iv:22.4,premium:5.6},
  {period:'Jul–Sep 2025',regime:'HIGH VOL',  rv:22.1,iv:29.6,premium:7.5},
  {period:'Oct–Dec 2025',regime:'HIGH VOL',  rv:20.4,iv:27.1,premium:6.7},
  {period:'Jan–Mar 2026',regime:'TRANSITION',rv:17.8,iv:23.9,premium:6.1},
  {period:'Apr–Jun 2026',regime:'NORMAL',    rv:18.4,iv:24.8,premium:6.4},
];

function AlphaVolatility() {
  const { useState } = React;
  const [ticker, setTicker] = useState('AU.SHF');
  const [lookback, setLookback] = useState(10);
  const [stddev, setStddev] = useState(2.0);
  const amber = 'var(--accent-amber)';

  // SVG line chart helper
  function LineChart({ series, colors, width=600, height=120, fillIdx }) {
    const allVals = series.flat();
    const mn = Math.min(...allVals), mx = Math.max(...allVals), rng = mx-mn||1;
    const W=width, H=height, pad={t:8,b:20,l:32,r:8};
    const iw=W-pad.l-pad.r, ih=H-pad.t-pad.b;
    const px=(i)=>pad.l+i*(iw/(series[0].length-1));
    const py=(v)=>pad.t+ih-(((v-mn)/rng)*ih);
    const path=(s)=>s.map((v,i)=>`${i===0?'M':'L'}${px(i)},${py(v)}`).join(' ');
    const step = Math.floor(series[0].length/6);
    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:'block'}}>
        {[0,0.25,0.5,0.75,1].map(t=>(
          <line key={t} x1={pad.l} x2={W-pad.r} y1={pad.t+ih*t} y2={pad.t+ih*t} stroke="rgba(255,255,255,0.06)" strokeWidth="1"/>
        ))}
        {fillIdx && series.length>2 && (() => {
          const upper=series[fillIdx[0]], lower=series[fillIdx[1]];
          const pts = [...upper.map((v,i)=>`${px(i)},${py(v)}`), ...[...lower].reverse().map((v,i,a)=>`${px(a.length-1-i)},${py(v)}`)].join(' ');
          return <polygon points={pts} fill="rgba(100,160,220,0.15)"/>;
        })()}
        {series.map((s,si)=>(
          <path key={si} d={path(s)} fill="none" stroke={colors[si]} strokeWidth={si===0?2:1.5} opacity={0.9}/>
        ))}
        {dates.filter((_,i)=>i%step===0).map((d,i)=>(
          <text key={i} x={px(i*step)} y={H-4} textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="8">{d}</text>
        ))}
        {[0,0.5,1].map(t=>{
          const v=(mn+rng*t).toFixed(0);
          return <text key={t} x={pad.l-4} y={pad.t+ih*(1-t)+3} textAnchor="end" fill="rgba(255,255,255,0.35)" fontSize="8">{v}</text>;
        })}
      </svg>
    );
  }

  function CardHeader({ title, badge }) {
    return (
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'11px 16px',background:'var(--surface-panel)',borderBottom:'1px solid var(--border-strong)',userSelect:'none'}}>
        <div style={{display:'flex',alignItems:'center',gap:'10px'}}>
          <span style={{font:'var(--type-h2)',fontSize:'13px',fontWeight:600,color:'var(--text-primary)'}}>{title}</span>
          {badge && <span style={{font:'var(--type-meta)',fontSize:'9px',color:'var(--text-muted)',background:'var(--surface-input)',padding:'2px 7px',borderRadius:'3px',border:'1px solid var(--border-default)'}}>{badge}</span>}
        </div>
      </div>
    );
  }

  function RegimeBadge({regime}) {
    const map={'LOW VOL':{bg:'rgba(52,211,153,0.15)',c:'#34d399'},'NORMAL':{bg:'rgba(59,130,246,0.15)',c:'var(--accent-cyan)'},
      'TRANSITION':{bg:`rgba(224,162,60,0.15)`,c:amber},'HIGH VOL':{bg:'rgba(239,68,68,0.15)',c:'#f87171'}};
    const s=map[regime]||map['NORMAL'];
    return <span style={{padding:'2px 7px',borderRadius:'3px',fontSize:'9px',fontWeight:700,background:s.bg,color:s.c}}>{regime}</span>;
  }

  return (
    <div style={{display:'flex',flexDirection:'column',gap:'10px'}}>
      <div>
        <h1 style={{margin:'0 0 3px',font:'var(--type-h1)',color:'var(--text-primary)'}}>Volatility Analysis</h1>
        <div style={{font:'var(--type-meta)',color:'var(--text-muted)'}}>IV term structure, Bollinger bands strategy, and regime history</div>
      </div>

      {/* Three-card row: Controls + Performance Table + Regime History */}
      <div style={{display:'grid',gridTemplateColumns:'220px 1fr 1fr',gap:'12px',alignItems:'start'}}>
        {/* Controls card */}
        <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
          <CardHeader title="Controls" />
          <div style={{padding:'12px 14px',display:'flex',flexDirection:'column',gap:'12px'}}>
            <div style={{display:'flex',flexDirection:'column',gap:'4px'}}>
              <div style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em'}}>Ticker</div>
              <select value={ticker} onChange={e=>setTicker(e.target.value)} style={{padding:'6px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'10px',cursor:'pointer'}}>
                {TICKERS.map(t=><option key={t}>{t}</option>)}
              </select>
            </div>
            <div style={{display:'flex',flexDirection:'column',gap:'4px'}}>
              <div style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em'}}>Lookback</div>
              <input type="number" value={lookback} min={5} max={60} onChange={e=>setLookback(+e.target.value)}
                style={{padding:'6px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'10px',textAlign:'right'}}/>
            </div>
            <div style={{display:'flex',flexDirection:'column',gap:'4px'}}>
              <div style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em'}}>Std Dev ×</div>
              <input type="number" value={stddev} min={1} max={4} step={0.5} onChange={e=>setStddev(+e.target.value)}
                style={{padding:'6px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'10px',textAlign:'right'}}/>
            </div>
            <button style={{padding:'6px 12px',background:'var(--positive)',color:'var(--navy-950)',border:'none',borderRadius:'4px',font:'var(--type-label)',fontSize:'10px',fontWeight:700,cursor:'pointer',width:'100%'}}>▶ Run</button>
            <button style={{padding:'6px 12px',background:'transparent',color:'var(--text-muted)',border:'1px solid var(--border-default)',borderRadius:'4px',font:'var(--type-label)',fontSize:'10px',cursor:'pointer',width:'100%'}}>↻ Refresh</button>
          </div>
        </div>

        {/* Performance Table */}
        <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
          <CardHeader title="Performance" />
          <div style={{overflowX:'auto'}}>
            <table style={{width:'100%',borderCollapse:'collapse',font:'var(--type-data)',fontSize:'10px'}}>
              <tbody>
                {[
                  {label:'Total Return',value:`${KPI_DATA.totalReturn.toFixed(1)}%`,positive:true},
                  {label:'Annualized Return',value:`${KPI_DATA.annReturn.toFixed(1)}%`,positive:true},
                  {label:'Volatility',value:`${KPI_DATA.volatility.toFixed(1)}%`},
                  {label:'Sharpe Ratio',value:KPI_DATA.sharpe.toFixed(2)},
                  {label:'Win Rate',value:`${KPI_DATA.winRate.toFixed(1)}%`,positive:true},
                  {label:'Max Drawdown',value:`${KPI_DATA.maxDD.toFixed(2)}%`},
                  {label:'Total Trades',value:KPI_DATA.trades},
                ].map((r,i)=>(
                  <tr key={i} style={{borderBottom:'1px solid rgba(255,255,255,0.04)',background:i%2===0?'transparent':'rgba(255,255,255,0.015)'}}>
                    <td style={{padding:'6px 12px',color:'var(--text-secondary)'}}>{r.label}</td>
                    <td style={{padding:'6px 12px',textAlign:'right',color:r.positive?'#34d399':amber,fontWeight:600}}>{r.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Regime History */}
        <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
          <CardHeader title="Regime History" badge="6 periods" />
          <div style={{overflowX:'auto'}}>
            <table style={{width:'100%',borderCollapse:'collapse',font:'var(--type-data)',fontSize:'10px'}}>
              <thead>
                <tr style={{background:'var(--surface-panel)',borderBottom:'1px solid var(--border-strong)'}}>
                  {['Period','Regime','RV (%)','IV (%)'].map(h=>(
                    <th key={h} style={{padding:'8px 12px',textAlign:['Period','Regime'].includes(h)?'left':'right',font:'var(--type-label)',fontSize:'8px',color:'var(--text-muted)',letterSpacing:'0.05em'}}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {REGIME_HISTORY.map((r,i)=>(
                  <tr key={i} style={{borderBottom:'1px solid rgba(255,255,255,0.04)',background:i===REGIME_HISTORY.length-1?'rgba(255,255,255,0.03)':i%2===0?'transparent':'rgba(255,255,255,0.015)'}}>
                    <td style={{padding:'6px 12px',color:'var(--text-secondary)',fontSize:'9px'}}>{r.period}</td>
                    <td style={{padding:'6px 12px'}}><RegimeBadge regime={r.regime}/></td>
                    <td style={{padding:'6px 12px',textAlign:'right',color:'var(--text-secondary)',fontSize:'9px'}}>{r.rv.toFixed(1)}</td>
                    <td style={{padding:'6px 12px',textAlign:'right',color:'var(--text-secondary)',fontSize:'9px'}}>{r.iv.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Three full-width charts in rows */}
      {/* IV Term Structure */}
      <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
        <CardHeader title="Implied Volatility Term Structure" />
        <div style={{padding:'12px 16px',display:'flex',gap:'12px',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)',borderBottom:'1px solid var(--border-strong)'}}>
          {[['#38bdf8','1M IV'],[amber,'2M IV'],['#f87171','3M IV']].map(([c,l])=>(
            <span key={l} style={{display:'flex',alignItems:'center',gap:'4px'}}>
              <span style={{width:'12px',height:'2px',background:c,display:'inline-block',borderRadius:'1px'}}></span>{l}
            </span>
          ))}
        </div>
        <div style={{padding:'12px 16px'}}><LineChart series={[IV1M,IV2M,IV3M]} colors={['#38bdf8',amber,'#f87171']} height={130}/></div>
      </div>

      {/* Bollinger Bands */}
      <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
        <CardHeader title="Mean Reversion: Bollinger Bands" />
        <div style={{padding:'12px 16px',display:'flex',gap:'12px',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)',borderBottom:'1px solid var(--border-strong)'}}>
          {[['#38bdf8','Mid (1M IV)'],[' rgba(100,160,220,0.4)','±1σ Band']].map(([c,l])=>(
            <span key={l} style={{display:'flex',alignItems:'center',gap:'4px'}}>
              <span style={{width:'12px',height:'2px',background:c,display:'inline-block',borderRadius:'1px'}}></span>{l}
            </span>
          ))}
        </div>
        <div style={{padding:'12px 16px'}}><LineChart series={[MID,UPPER,LOWER]} colors={['#38bdf8','rgba(100,180,255,0.4)','rgba(100,180,255,0.4)']} height={150} fillIdx={[1,2]}/></div>
      </div>

      {/* Cumulative Return */}
      <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
        <CardHeader title="Strategy Cumulative Return" />
        <div style={{padding:'12px 16px'}}><LineChart series={[CUM]} colors={['#38bdf8']} height={130}/></div>
      </div>
    </div>
  );
}
window.AlphaVolatility = AlphaVolatility;
