// Alpha Book > Volatility — redesigned with controls, KPI bar, charts, regime history
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

// Regime history (keep from original)
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
  const cyan  = 'var(--accent-cyan)';

  // SVG line chart helper
  function LineChart({ series, colors, width=600, height=120, labels, fillIdx }) {
    const allVals = series.flat();
    const mn = Math.min(...allVals), mx = Math.max(...allVals), rng = mx-mn||1;
    const W=width, H=height, pad={t:8,b:20,l:32,r:8};
    const iw=W-pad.l-pad.r, ih=H-pad.t-pad.b;
    const px=(i)=>pad.l+i*(iw/(series[0].length-1));
    const py=(v)=>pad.t+ih-(((v-mn)/rng)*ih);
    const path=(s)=>s.map((v,i)=>`${i===0?'M':'L'}${px(i)},${py(v)}`).join(' ');
    // X axis labels (sparse)
    const step = Math.floor(series[0].length/6);
    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:'block'}}>
        {/* grid */}
        {[0,0.25,0.5,0.75,1].map(t=>(
          <line key={t} x1={pad.l} x2={W-pad.r} y1={pad.t+ih*t} y2={pad.t+ih*t} stroke="rgba(255,255,255,0.06)" strokeWidth="1"/>
        ))}
        {/* fill band between index 1 and 2 (Bollinger) */}
        {fillIdx && series.length>2 && (() => {
          const upper=series[fillIdx[0]], lower=series[fillIdx[1]];
          const pts = [...upper.map((v,i)=>`${px(i)},${py(v)}`), ...[...lower].reverse().map((v,i,a)=>`${px(a.length-1-i)},${py(v)}`)].join(' ');
          return <polygon points={pts} fill="rgba(100,160,220,0.15)"/>;
        })()}
        {/* lines */}
        {series.map((s,si)=>(
          <path key={si} d={path(s)} fill="none" stroke={colors[si]} strokeWidth={si===0?2:1.5} opacity={0.9}/>
        ))}
        {/* x axis labels */}
        {dates.filter((_,i)=>i%step===0).map((d,i)=>(
          <text key={i} x={px(i*step)} y={H-4} textAnchor="middle" fill="rgba(255,255,255,0.35)" fontSize="8">{d}</text>
        ))}
        {/* y axis */}
        {[0,0.5,1].map(t=>{
          const v=(mn+rng*t).toFixed(0);
          return <text key={t} x={pad.l-4} y={pad.t+ih*(1-t)+3} textAnchor="end" fill="rgba(255,255,255,0.35)" fontSize="8">{v}</text>;
        })}
      </svg>
    );
  }

  function ChartCard({ title, children, legend }) {
    return (
      <div style={{border:'1px solid var(--border-strong)',borderRadius:'6px',overflow:'hidden',background:'var(--surface-panel)'}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'8px 12px',borderBottom:'1px solid var(--border-strong)'}}>
          <span style={{font:'var(--type-label)',fontSize:'10px',color:'var(--text-secondary)'}}>{title}</span>
          {legend && <div style={{display:'flex',gap:'10px'}}>{legend}</div>}
        </div>
        <div style={{padding:'8px 12px'}}>{children}</div>
      </div>
    );
  }

  function LegendDot({color,label}) {
    return <span style={{display:'flex',alignItems:'center',gap:'4px',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)'}}>
      <span style={{width:'16px',height:'2px',background:color,display:'inline-block',borderRadius:'1px'}}></span>{label}
    </span>;
  }

  function RegimeBadge({regime}) {
    const map={'LOW VOL':{bg:'rgba(52,211,153,0.15)',c:'#34d399'},'NORMAL':{bg:'rgba(59,130,246,0.15)',c:cyan},
      'TRANSITION':{bg:`rgba(224,162,60,0.15)`,c:amber},'HIGH VOL':{bg:'rgba(239,68,68,0.15)',c:'#f87171'}};
    const s=map[regime]||map['NORMAL'];
    return <span style={{padding:'2px 7px',borderRadius:'3px',fontSize:'9px',fontWeight:700,background:s.bg,color:s.c}}>{regime}</span>;
  }

  return (
    <div style={{display:'flex',flexDirection:'column',gap:'12px'}}>
      {/* Controls */}
      <div style={{display:'flex',alignItems:'center',gap:'12px',flexWrap:'wrap',padding:'10px 14px',
        background:'var(--surface-panel)',border:'1px solid var(--border-strong)',borderRadius:'6px'}}>
        <div style={{display:'flex',alignItems:'center',gap:'6px'}}>
          <span style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em',whiteSpace:'nowrap'}}>TICKER</span>
          <select value={ticker} onChange={e=>setTicker(e.target.value)} style={{padding:'5px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'11px',cursor:'pointer'}}>
            {TICKERS.map(t=><option key={t}>{t}</option>)}
          </select>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:'6px'}}>
          <span style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em',whiteSpace:'nowrap'}}>LOOKBACK</span>
          <input type="number" value={lookback} min={5} max={60} onChange={e=>setLookback(+e.target.value)}
            style={{width:'52px',padding:'5px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'11px',textAlign:'right'}}/>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:'6px'}}>
          <span style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em',whiteSpace:'nowrap'}}>STD DEV ×</span>
          <input type="number" value={stddev} min={1} max={4} step={0.5} onChange={e=>setStddev(+e.target.value)}
            style={{width:'52px',padding:'5px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'11px',textAlign:'right'}}/>
        </div>
        <button style={{padding:'6px 14px',background:'var(--positive)',color:'var(--navy-950)',border:'none',borderRadius:'4px',font:'var(--type-label)',fontSize:'10px',fontWeight:700,cursor:'pointer'}}>▶ Run Analysis</button>
        <button style={{padding:'6px 12px',background:'transparent',color:'var(--text-muted)',border:'1px solid var(--border-default)',borderRadius:'4px',font:'var(--type-label)',fontSize:'10px',cursor:'pointer'}}>↻ Refresh Data</button>
        <span style={{font:'var(--type-meta)',fontSize:'9px',color:'var(--text-muted)',marginLeft:'auto'}}>
          Analysis completed @ 07:46:17 | {ticker} | Lookback: {lookback} days | σ multiplier: {stddev.toFixed(1)}
        </span>
      </div>

      {/* KPI bar */}
      <div style={{display:'grid',gridTemplateColumns:'repeat(8,1fr)',gap:'0',border:'1px solid var(--border-strong)',borderRadius:'6px',overflow:'hidden',background:'var(--surface-panel)'}}>
        {[
          {label:'TICKER',       value:KPI_DATA.ticker,   plain:true},
          {label:'1M IV',        value:KPI_DATA.iv1m.toFixed(4)},
          {label:'2M IV',        value:KPI_DATA.iv2m.toFixed(4)},
          {label:'3M IV',        value:KPI_DATA.iv3m.toFixed(4)},
          {label:'SIGNAL',       value:KPI_DATA.signal,   plain:true},
          {label:'TOTAL RETURN', value:`${KPI_DATA.totalReturn.toFixed(2)}%`, positive:true},
          {label:'ANN. RETURN',  value:`${KPI_DATA.annReturn.toFixed(2)}%`,   positive:true},
          {label:'VOLATILITY',   value:`${KPI_DATA.volatility.toFixed(2)}%`},
          {label:'SHARPE',       value:KPI_DATA.sharpe.toFixed(2)},
          {label:'WIN RATE',     value:`${KPI_DATA.winRate.toFixed(2)}%`},
          {label:'MAX DRAWDOWN', value:`${KPI_DATA.maxDD.toFixed(2)}%`,       negative:true},
          {label:'NUM TRADES',   value:KPI_DATA.trades},
        ].slice(0,8).map((k,i)=>(
          <div key={i} style={{padding:'8px 10px',borderRight:i<7?'1px solid var(--border-strong)':'none'}}>
            <div style={{font:'var(--type-label)',fontSize:'8px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.05em',marginBottom:'3px'}}>{k.label}</div>
            <div style={{font:'var(--type-data)',fontSize:'12px',fontWeight:700,
              color:k.positive?'#34d399':k.negative?'#f87171':k.plain?'var(--text-primary)':amber}}>{k.value}</div>
          </div>
        ))}
      </div>
      <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:'0',border:'1px solid var(--border-strong)',borderRadius:'6px',overflow:'hidden',background:'var(--surface-panel)'}}>
        {[
          {label:'TOTAL RETURN',value:`${KPI_DATA.totalReturn.toFixed(2)}%`,positive:true},
          {label:'ANN. RETURN', value:`${KPI_DATA.annReturn.toFixed(2)}%`, positive:true},
          {label:'WIN RATE',    value:`${KPI_DATA.winRate.toFixed(2)}%`},
          {label:'MAX DRAWDOWN',value:`${KPI_DATA.maxDD.toFixed(2)}%`,    negative:true},
          {label:'VOLATILITY',  value:`${KPI_DATA.volatility.toFixed(2)}%`},
          {label:'SHARPE',      value:KPI_DATA.sharpe.toFixed(2)},
          {label:'NUM TRADES',  value:KPI_DATA.trades},
          {label:'SIGNAL',      value:KPI_DATA.signal,plain:true},
        ].map((k,i)=>(
          <div key={i} style={{padding:'8px 10px',borderRight:i%4<3?'1px solid var(--border-strong)':'none',borderTop:'1px solid var(--border-strong)'}}>
            <div style={{font:'var(--type-label)',fontSize:'8px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.05em',marginBottom:'3px'}}>{k.label}</div>
            <div style={{font:'var(--type-data)',fontSize:'12px',fontWeight:700,
              color:k.positive?'#34d399':k.negative?'#f87171':k.plain?'var(--text-primary)':amber}}>{k.value}</div>
          </div>
        ))}
      </div>

      {/* 4 charts */}
      <ChartCard title="Implied Volatility Term Structure" legend={[<LegendDot key="1m" color="#38bdf8" label="1M IV"/>,<LegendDot key="2m" color={amber} label="2M IV"/>,<LegendDot key="3m" color="#f87171" label="3M IV"/>]}>
        <LineChart series={[IV1M,IV2M,IV3M]} colors={['#38bdf8',amber,'#f87171']} height={130}/>
      </ChartCard>

      <ChartCard title="Mean Reversion Strategy — Bollinger Bands" legend={[<LegendDot key="s" color="#f87171" label="Short Signal"/>,<LegendDot key="l" color="#34d399" label="Long Signal"/>,<LegendDot key="m" color="#38bdf8" label="1M IV"/>]}>
        <LineChart series={[MID,UPPER,LOWER]} colors={['#38bdf8','rgba(100,180,255,0.4)','rgba(100,180,255,0.4)']} height={150} fillIdx={[1,2]}/>
      </ChartCard>

      <ChartCard title="Strategy Cumulative Return Curve">
        <LineChart series={[CUM]} colors={['#38bdf8']} height={110}/>
      </ChartCard>

      <ChartCard title="Term Structure Slope Z-Score (1M-3M)" legend={[<LegendDot key="p" color="#34d399" label="+1.50"/>,<LegendDot key="n" color="#f87171" label="-0.95"/>]}>
        <svg width="100%" viewBox="0 0 600 80" style={{display:'block'}}>
          <line x1={32} x2={592} y1={40} y2={40} stroke="rgba(255,255,255,0.15)" strokeWidth="1"/>
          <line x1={32} x2={592} y1={20} y2={20} stroke="rgba(52,211,153,0.4)" strokeWidth="1" strokeDasharray="4,3"/>
          <line x1={32} x2={592} y1={60} y2={60} stroke="rgba(239,68,68,0.4)"   strokeWidth="1" strokeDasharray="4,3"/>
          {ZSLOPE.map((v,i)=>{
            const x=32+i*(560/(N-1)), y=40-v*8;
            return <line key={i} x1={x} y1={40} x2={x} y2={y} stroke={v>=0?'#38bdf8':'#38bdf8'} strokeWidth="1.5" opacity="0.7"/>;
          })}
          <text x={596} y={23} fill="rgba(52,211,153,0.8)" fontSize="8" textAnchor="end">+1.50</text>
          <text x={596} y={63} fill="rgba(239,68,68,0.8)"  fontSize="8" textAnchor="end">-0.95</text>
        </svg>
      </ChartCard>

      {/* Regime History (preserved from original) */}
      <div>
        <div style={{font:'var(--type-label)',color:'var(--text-muted)',fontSize:'9px',textTransform:'uppercase',letterSpacing:'0.07em',marginBottom:'8px'}}>Regime History</div>
        <div style={{border:'1px solid var(--border-strong)',borderRadius:'6px',overflow:'hidden'}}>
          <table style={{width:'100%',borderCollapse:'collapse',font:'var(--type-data)',fontSize:'11px'}}>
            <thead>
              <tr style={{background:'var(--surface-panel)',borderBottom:'1px solid var(--border-strong)'}}>
                {['Period','Regime','RV','IV','Premium'].map(h=>(
                  <th key={h} style={{padding:'7px 10px',textAlign:['Period','Regime'].includes(h)?'left':'right',
                    font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',letterSpacing:'0.05em'}}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {REGIME_HISTORY.map((r,i)=>(
                <tr key={i} style={{borderBottom:'1px solid rgba(255,255,255,0.04)',background:i===REGIME_HISTORY.length-1?'rgba(255,255,255,0.03)':i%2===0?'transparent':'rgba(255,255,255,0.015)'}}>
                  <td style={{padding:'5px 10px',color:'var(--text-muted)',fontSize:'10px'}}>{r.period}</td>
                  <td style={{padding:'5px 10px'}}><RegimeBadge regime={r.regime}/></td>
                  <td style={{padding:'5px 10px',textAlign:'right',color:'var(--text-secondary)'}}>{r.rv.toFixed(1)}</td>
                  <td style={{padding:'5px 10px',textAlign:'right',color:'var(--text-secondary)'}}>{r.iv.toFixed(1)}</td>
                  <td style={{padding:'5px 10px',textAlign:'right',color:amber,fontWeight:600}}>+{r.premium.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
window.AlphaVolatility = AlphaVolatility;
