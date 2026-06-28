// Alpha Book > Pairs — consistent with Candidates/Portfolio pattern
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
  const amber = 'var(--accent-amber)';

  function PairChart({ pair }) {
    const N = 28;
    const spread = genPairData(N, pair.last+(pair.yMax-pair.yMin)*0.4, pair.trend==='down'?-0.05:0.03, (pair.yMax-pair.yMin)*0.08);
    const mn=pair.yMin, mx=pair.yMax, rng=mx-mn||1;
    const W=700, H=160, pad={t:12,b:24,l:36,r:12};
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

    const bandPts=[...upBand.map((v,i)=>`${px(i)},${py(v)}`), ...[...loBand].reverse().map((v,i,a)=>`${px(a.length-1-i)},${py(v)}`)].join(' ');
    const monthLabels=['May 17','May 24','May 31','Jun 7','Jun 14','Jun 21'];

    const zAbs=Math.abs(pair.z);
    const zColor=zAbs>=2?'#f87171':zAbs>=1.5?amber:'#6b7280';

    return (
      <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
        <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'11px 16px',background:'var(--surface-panel)',borderBottom:'1px solid var(--border-strong)'}}>
          <div style={{display:'flex',alignItems:'center',gap:'10px'}}>
            <span style={{font:'var(--type-h2)',fontSize:'13px',fontWeight:600,color:'var(--text-primary)'}}>
              {pair.a} <span style={{color:'var(--text-muted)',fontWeight:400,fontSize:'11px'}}>vs</span> {pair.b}
            </span>
          </div>
          <div style={{display:'flex',gap:'12px',alignItems:'center',font:'var(--type-meta)',fontSize:'10px'}}>
            <span style={{color:'var(--text-muted)'}}>last <span style={{color:'var(--text-primary)',fontWeight:600}}>{pair.last.toFixed(1)} bp</span></span>
            <span style={{color:'var(--text-muted)'}}>β <span style={{color:'var(--text-secondary)'}}>{pair.beta>=0?'+':''}{pair.beta.toFixed(3)}</span></span>
            <span style={{color:'var(--text-muted)'}}>z <span style={{color:zColor,fontWeight:700}}>{pair.z>=0?'+':''}{pair.z.toFixed(1)}σ</span></span>
          </div>
        </div>
        <div style={{display:'flex',gap:'12px',padding:'8px 16px 0',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)',borderBottom:'1px solid var(--border-strong)'}}>
          {[['#38bdf8','OLS Trend'],['#9ca3af','• Spread'],['rgba(100,160,220,0.3)','±1σ Confidence Band']].map(([c,l])=>(
            <span key={l} style={{display:'flex',alignItems:'center',gap:'4px'}}>
              <span style={{width:'12px',height:'2px',background:c,display:'inline-block',borderRadius:'1px'}}></span>{l}
            </span>
          ))}
        </div>
        <div style={{padding:'12px 16px'}}>
          <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:'block'}}>
            {[0,0.33,0.67,1].map(t=>(
              <line key={t} x1={pad.l} x2={W-pad.r} y1={pad.t+ih*t} y2={pad.t+ih*t} stroke="rgba(255,255,255,0.05)" strokeWidth="1"/>
            ))}
            <polygon points={bandPts} fill="rgba(100,160,220,0.18)"/>
            {spread.map((v,i)=>(
              <circle key={i} cx={px(i)} cy={py(v)} r="2.5" fill="#94a3b8" opacity="0.7"/>
            ))}
            <path d={`M${px(0)},${py(trendY(0))} L${px(N-1)},${py(trendY(N-1))}`} fill="none" stroke="#38bdf8" strokeWidth="1.5" opacity="0.9"/>
            {[mn, (mn+mx)/2, mx].map((v,i)=>(
              <text key={i} x={pad.l-4} y={py(v)+3} textAnchor="end" fill="rgba(255,255,255,0.35)" fontSize="8">{v.toFixed(0)}</text>
            ))}
            {monthLabels.map((l,i)=>(
              <text key={i} x={pad.l+i*(iw/5)} y={H-6} textAnchor="middle" fill="rgba(255,255,255,0.3)" fontSize="8">{l}</text>
            ))}
          </svg>
        </div>
      </div>
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

  return (
    <div style={{display:'flex',flexDirection:'column',gap:'10px'}}>
      <div>
        <h1 style={{margin:'0 0 3px',font:'var(--type-h1)',color:'var(--text-primary)'}}>Pairs Analysis</h1>
        <div style={{font:'var(--type-meta)',color:'var(--text-muted)'}}>Relative value spreads with OLS trends and confidence bands</div>
      </div>

      {/* Top row: Controls (left) + Z-Score Thresholds (right) */}
      <div style={{display:'flex',gap:'12px',alignItems:'flex-start'}}>
        {/* Controls card — narrow, fixed width */}
        <div style={{width:'220px',flexShrink:0,border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
          <CardHeader title="Controls" />
          <div style={{padding:'12px 14px',display:'flex',flexDirection:'column',gap:'12px'}}>
            <div style={{display:'flex',flexDirection:'column',gap:'4px'}}>
              <div style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em'}}>Lookback Days</div>
              <input type="number" value={lookback} min={10} max={365} onChange={e=>setLookback(+e.target.value)}
                style={{padding:'6px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'10px',textAlign:'right'}}/>
            </div>
            <button style={{padding:'6px 12px',background:'var(--surface-panel)',color:'var(--text-secondary)',border:'1px solid var(--border-default)',borderRadius:'4px',font:'var(--type-label)',fontSize:'10px',cursor:'pointer',width:'100%'}}>⚙ Configure</button>
            <button style={{padding:'6px 12px',background:amber,color:'var(--navy-950)',border:'none',borderRadius:'4px',font:'var(--type-label)',fontSize:'10px',fontWeight:700,cursor:'pointer',width:'100%'}}>↻ Refresh</button>
            <div style={{font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)',marginTop:'4px'}}>Last: 07:46:05</div>
          </div>
        </div>

        {/* Z-Score Thresholds — flex 1 */}
        <div style={{flex:1,minWidth:0,border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
          <CardHeader title="Z-Score Thresholds" badge="Color-coded signal levels" />
          <div style={{padding:'12px 16px',display:'flex',alignItems:'center',gap:'20px',font:'var(--type-meta)',fontSize:'10px'}}>
            {[['#6b7280','|z| < 1.5','Neutral'],[amber,'1.5 ≤ |z| < 2.0','Watch'],['#f87171','|z| ≥ 2.0','Signal']].map(([c,range,label])=>(
              <div key={label} style={{display:'flex',alignItems:'center',gap:'8px',flex:1}}>
                <span style={{width:'12px',height:'12px',borderRadius:'50%',background:c,display:'inline-block',flexShrink:0}}></span>
                <div style={{display:'flex',flexDirection:'column',gap:'1px',minWidth:0}}>
                  <span style={{color:'var(--text-secondary)',fontWeight:600}}>{label}</span>
                  <span style={{color:'var(--text-muted)',fontSize:'9px'}}>{range}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Chart grid */}
      <div style={{display:'grid',gridTemplateColumns:'1fr 1fr',gap:'10px'}}>
        {PAIRS_DATA.map((p,i)=><PairChart key={i} pair={p}/>)}
      </div>
    </div>
  );
}
window.AlphaPairs = AlphaPairs;
