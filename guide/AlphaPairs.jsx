// Alpha Book > Pairs — redesigned with 2x2 chart grid
const _ns_apairs = window.AtlasNexusDesignSystem_988df3;

const PAIRS_DATA = [
  { a:'260010.IB', b:'260008.IB', last:30.2, beta:-0.049, z:+1.6, zColor:'#f87171',  trend:'down',  yMin:27,  yMax:31,  },
  { a:'2600002.IB',b:'260010.IB', last:49.1, beta:+0.017, z:+0.1, zColor:'#6b7280',  trend:'up',    yMin:48,  yMax:49.5,},
  { a:'260205.IB', b:'260010.IB', last:4.2,  beta:-0.224, z:+0.0, zColor:'#6b7280',  trend:'down',  yMin:2,   yMax:14,  },
  { a:'260008.IB', b:'FR007S5Y.IR',last:-9.5,beta:-0.064, z:+1.6, zColor:'#f87171',  trend:'up',    yMin:-14, yMax:-6,  },
];

function genPairData(n, start, trend, noise) {
  const pts=[]; let v=start;
  for(let i=0;i<n;i++){v+=trend+(Math.random()-0.5)*noise; pts.push(v);}
  return pts;
}

function AlphaPairs() {
  const { useState } = React;
  const [lookback, setLookback] = useState(91);
  const cyan = 'var(--accent-cyan)';
  const amber = 'var(--accent-amber)';

  function PairChart({ pair }) {
    const N = 28;
    const spread = genPairData(N, pair.last+(pair.yMax-pair.yMin)*0.4, pair.trend==='down'?-0.05:0.03, (pair.yMax-pair.yMin)*0.08);
    const mn=pair.yMin, mx=pair.yMax, rng=mx-mn||1;
    const W=500, H=160, pad={t:12,b:24,l:36,r:12};
    const iw=W-pad.l-pad.r, ih=H-pad.t-pad.b;
    const px=i=>pad.l+i*(iw/(N-1));
    const py=v=>pad.t+ih-(((v-mn)/rng)*ih);

    // OLS trend line
    const xs=spread.map((_,i)=>i), meanX=xs.reduce((a,b)=>a+b,0)/N, meanY=spread.reduce((a,b)=>a+b,0)/N;
    const num=xs.reduce((a,x,i)=>a+(x-meanX)*(spread[i]-meanY),0);
    const den=xs.reduce((a,x)=>a+(x-meanX)**2,0);
    const slope=num/(den||1), intercept=meanY-slope*meanX;
    const trendY=(i)=>slope*i+intercept;

    // Confidence band (±1σ)
    const resid=spread.map((v,i)=>v-trendY(i));
    const sig=Math.sqrt(resid.reduce((a,r)=>a+r*r,0)/N);
    const upBand=spread.map((_,i)=>trendY(i)+sig);
    const loBand=spread.map((_,i)=>trendY(i)-sig);

    const spreadPath=spread.map((v,i)=>`${i===0?'M':'L'}${px(i)},${py(v)}`).join(' ');
    const trendPath=`M${px(0)},${py(trendY(0))} L${px(N-1)},${py(trendY(N-1))}`;
    const bandPts=[...upBand.map((v,i)=>`${px(i)},${py(v)}`), ...[...loBand].reverse().map((v,i,a)=>`${px(a.length-1-i)},${py(v)}`)].join(' ');

    // X axis labels (monthly)
    const monthLabels=['May 17','May 24','May 31','Jun 7','Jun 14','Jun 21'];

    const zAbs=Math.abs(pair.z);
    const zColor=zAbs>=2?'#f87171':zAbs>=1.5?amber:'#6b7280';

    return (
      <div style={{border:'1px solid var(--border-strong)',borderRadius:'6px',overflow:'hidden',background:'var(--surface-panel)'}}>
        {/* Header */}
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'8px 12px',borderBottom:'1px solid var(--border-strong)'}}>
          <span style={{font:'var(--type-data)',fontSize:'12px',fontWeight:700,color:'var(--text-primary)'}}>
            {pair.a} <span style={{color:'var(--text-muted)',fontWeight:400,fontSize:'10px'}}>VS</span> {pair.b}
          </span>
          <div style={{display:'flex',gap:'12px',alignItems:'center',font:'var(--type-meta)',fontSize:'10px'}}>
            <span style={{color:'var(--text-muted)'}}>last <span style={{color:'var(--text-primary)',fontWeight:600}}>{pair.last.toFixed(1)} bp</span></span>
            <span style={{color:'var(--text-muted)'}}>β <span style={{color:'var(--text-secondary)'}}>{pair.beta>=0?'+':''}{pair.beta.toFixed(3)}/d</span></span>
            <span style={{color:'var(--text-muted)'}}>z <span style={{color:zColor,fontWeight:700}}>{pair.z>=0?'+':''}{pair.z.toFixed(1)}σ</span></span>
          </div>
        </div>
        {/* Legend */}
        <div style={{display:'flex',gap:'12px',padding:'6px 12px 0',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)'}}>
          {[['#38bdf8','Trend (OLS)'],['#9ca3af','• Spread'],['rgba(100,160,220,0.3)','±1σ confidence']].map(([c,l])=>(
            <span key={l} style={{display:'flex',alignItems:'center',gap:'4px'}}>
              <span style={{width:'14px',height:'2px',background:c,display:'inline-block',borderRadius:'1px'}}></span>{l}
            </span>
          ))}
        </div>
        {/* Chart */}
        <div style={{padding:'4px 8px 8px'}}>
          <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:'block'}}>
            {/* grid */}
            {[0,0.33,0.67,1].map(t=>(
              <line key={t} x1={pad.l} x2={W-pad.r} y1={pad.t+ih*t} y2={pad.t+ih*t} stroke="rgba(255,255,255,0.05)" strokeWidth="1"/>
            ))}
            {/* confidence band */}
            <polygon points={bandPts} fill="rgba(100,160,220,0.18)"/>
            {/* spread dots */}
            {spread.map((v,i)=>(
              <circle key={i} cx={px(i)} cy={py(v)} r="2.5" fill="#94a3b8" opacity="0.7"/>
            ))}
            {/* trend line */}
            <path d={trendPath} fill="none" stroke="#38bdf8" strokeWidth="1.5" opacity="0.9"/>
            {/* y axis labels */}
            {[mn, (mn+mx)/2, mx].map((v,i)=>(
              <text key={i} x={pad.l-4} y={py(v)+3} textAnchor="end" fill="rgba(255,255,255,0.35)" fontSize="8">{v.toFixed(0)}</text>
            ))}
            {/* y axis title */}
            <text x={8} y={H/2} textAnchor="middle" fill="rgba(255,255,255,0.3)" fontSize="8"
              transform={`rotate(-90,8,${H/2})`}>Spread (bp)</text>
            {/* x axis labels */}
            {monthLabels.map((l,i)=>(
              <text key={i} x={pad.l+i*(iw/5)} y={H-6} textAnchor="middle" fill="rgba(255,255,255,0.3)" fontSize="8">{l}</text>
            ))}
          </svg>
        </div>
      </div>
    );
  }

  return (
    <div style={{display:'flex',flexDirection:'column',gap:'14px'}}>
      {/* Controls */}
      <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',flexWrap:'wrap',gap:'10px'}}>
        <div>
          <h1 style={{margin:'0 0 3px',font:'var(--type-h1)',color:'var(--text-primary)'}}>Pairs Analysis</h1>
          <div style={{font:'var(--type-meta)',color:'var(--text-muted)'}}>Interactive spread analysis with confidence bands (in basis points)</div>
        </div>
        <div style={{display:'flex',alignItems:'center',gap:'10px'}}>
          <div style={{display:'flex',alignItems:'center',gap:'6px'}}>
            <span style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em'}}>Lookback Days:</span>
            <input type="number" value={lookback} min={10} max={365} onChange={e=>setLookback(+e.target.value)}
              style={{width:'56px',padding:'5px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',
                borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'11px',textAlign:'right'}}/>
          </div>
          <button style={{padding:'6px 12px',background:'var(--surface-panel)',color:'var(--text-secondary)',border:'1px solid var(--border-default)',
            borderRadius:'4px',font:'var(--type-label)',fontSize:'10px',cursor:'pointer'}}>⚙ Configure Pairs</button>
          <button style={{padding:'6px 12px',background:amber,color:'var(--navy-950)',border:'none',
            borderRadius:'4px',font:'var(--type-label)',fontSize:'10px',fontWeight:700,cursor:'pointer'}}>↻ Refresh</button>
          <span style={{font:'var(--type-meta)',fontSize:'9px',color:'var(--text-muted)'}}>Last updated: 2026-06-26 07:46:05</span>
        </div>
      </div>

      {/* Z-score legend */}
      <div style={{display:'flex',alignItems:'center',gap:'16px',padding:'8px 12px',background:'var(--surface-panel)',
        border:'1px solid var(--border-strong)',borderRadius:'6px',font:'var(--type-meta)',fontSize:'10px'}}>
        <span style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em'}}>Z-Score Colour Thresholds</span>
        {[['#6b7280','Neutral: |z| < 1.5'],[amber,'Watch: 1.5 ≤ |z| < 2.0'],['#f87171','Signal: |z| ≥ 2.0']].map(([c,l])=>(
          <span key={l} style={{display:'flex',alignItems:'center',gap:'5px',color:'var(--text-secondary)'}}>
            <span style={{width:'8px',height:'8px',borderRadius:'50%',background:c,display:'inline-block'}}></span>{l}
          </span>
        ))}
      </div>

      {/* 2x2 chart grid */}
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'12px'}}>
        {PAIRS_DATA.map((p,i)=><PairChart key={i} pair={p}/>)}
      </div>
    </div>
  );
}
window.AlphaPairs = AlphaPairs;
