// Alpha Book > Spread — redesigned explorer with sidebar + charts
const _ns_as = window.AtlasNexusDesignSystem_988df3;

const SPREAD_TYPES = ['Curve & Cross-Ass...','Swap Spread','Tenor Spread','Bond Swap','IRS Curve'];
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const YEAR_OPTIONS = ['3 years','5 years','7 years','10 years'];

// Z-score bar data for daily spread stats
const DAILY_SPREADS = [
  {id:'CGB-5s10s',z:0.8},{id:'CGB-10s20s',z:0.5},{id:'CGB-10s30s',z:-0.3},{id:'CDB-5s10s',z:-0.5},
  {id:'CDBCGB-5y',z:-1.1},{id:'CDBCGB-10y',z:-1.3},{id:'CGBRepo7d-1y',z:0.3},{id:'CGBRepo7d-2y',z:0.2},
  {id:'CGBRepo7d-5y',z:-0.2},{id:'CGBRepo7d-10y',z:-0.4},{id:'ICPRepo7d-3m',z:-0.7},{id:'ICPRepo7d-6m',z:-0.9},
  {id:'ICPRepo7d-9m',z:-1.0},{id:'ICPRepo7d-1y',z:-0.8},
];

// Synthetic time series
function genTs(n, base, amp, trend=0) {
  const pts=[]; let v=base;
  for(let i=0;i<n;i++){v+=(Math.random()-0.5)*amp+trend; pts.push(Math.max(base*0.4,v));}
  return pts;
}
const N=60, SPREAD_TS=genTs(N,22,1.5,0.04);
const CARRY_BUY=SPREAD_TS.map(v=>v+5+Math.random()*2);
const CARRY_SELL=SPREAD_TS.map(v=>v-5-Math.random()*2);
const UPPER_BAND=SPREAD_TS.map(v=>v+4);
const LOWER_BAND=SPREAD_TS.map(v=>Math.max(12,v-4));

// Seasonal pattern (per year lines)
const YEARS=['2022','2023','2024','2025','2026'];
const SEASONAL=YEARS.map(()=>Array.from({length:12},()=>(Math.random()-0.5)*0.15));
const HIST_MEAN=Array.from({length:12},(_,i)=>SEASONAL.reduce((a,s)=>a+s[i],0)/YEARS.length);

const MONTHLY_STATS=[
  {m:'Jan',dir:'↓',cons:'55%',avg:'+0.0',obs:'n=11',p:'p=0.50'},
  {m:'Feb',dir:'↓',cons:'67%',avg:'-0.0',obs:'n=12',p:'p=0.19'},
  {m:'Mar',dir:'↑',cons:'58%',avg:'+0.0',obs:'n=12',p:'p=0.39'},
  {m:'Apr',dir:'↓',cons:'58%',avg:'+0.0',obs:'n=12',p:'p=0.39'},
  {m:'May',dir:'—',cons:'50%',avg:'-0.0',obs:'n=12',p:'p=0.61'},
  {m:'Jun',dir:'↓',cons:'58%',avg:'-0.0',obs:'n=12',p:'p=0.39',highlight:true},
  {m:'Jul',dir:'↓',cons:'55%',avg:'+0.0',obs:'n=11',p:'p=0.50'},
  {m:'Aug',dir:'↓',cons:'73%',avg:'-0.0',obs:'n=11',p:'p=0.11'},
  {m:'Sep',dir:'↓',cons:'55%',avg:'-0.0',obs:'n=11',p:'p=0.50'},
  {m:'Oct',dir:'↑',cons:'73%',avg:'+0.0',obs:'n=11',p:'p=0.11'},
  {m:'Nov',dir:'↓',cons:'55%',avg:'-0.0',obs:'n=11',p:'p=0.50'},
  {m:'Dec',dir:'↑',cons:'55%',avg:'-0.0',obs:'n=11',p:'p=0.50'},
];

function AlphaSpread() {
  const { useState } = React;
  const [spreadType, setSpreadType] = useState(SPREAD_TYPES[0]);
  const [month, setMonth] = useState('Jun');
  const [years, setYears] = useState('5 years');
  const amber = 'var(--accent-amber)';
  const cyan  = 'var(--accent-cyan)';

  // Chart helpers
  function makePath(data, px, py) { return data.map((v,i)=>`${i===0?'M':'L'}${px(i)},${py(v)}`).join(' '); }

  function SpreadTimeSeries() {
    const W=700,H=180,pad={t:12,b:24,l:36,r:60};
    const iw=W-pad.l-pad.r,ih=H-pad.t-pad.b;
    const allVals=[...SPREAD_TS,...CARRY_BUY,...CARRY_SELL,...UPPER_BAND,...LOWER_BAND];
    const mn=Math.min(...allVals)-1,mx=Math.max(...allVals)+1,rng=mx-mn||1;
    const px=i=>pad.l+i*(iw/(N-1));
    const py=v=>pad.t+ih-(((v-mn)/rng)*ih);
    // Right axis for carry (scaled)
    const cmn=Math.min(...CARRY_BUY,...CARRY_SELL),cmx=Math.max(...CARRY_BUY,...CARRY_SELL),crng=cmx-cmn||1;
    const months=['Jul 25','Sep 25','Nov 25','Jan 26','Mar 26','May 26'];
    const step=Math.floor(N/5);
    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:'block'}}>
        {[0,0.25,0.5,0.75,1].map(t=>(
          <line key={t} x1={pad.l} x2={W-pad.r} y1={pad.t+ih*t} y2={pad.t+ih*t} stroke="rgba(255,255,255,0.06)" strokeWidth="1"/>
        ))}
        {/* Bollinger band */}
        <polygon points={[...UPPER_BAND.map((v,i)=>`${px(i)},${py(v)}`), ...[...LOWER_BAND].reverse().map((v,i,a)=>`${px(a.length-1-i)},${py(v)}`)].join(' ')} fill="rgba(100,160,220,0.12)"/>
        {/* dashed mean lines */}
        {[py((mn+mx)/2+3), py((mn+mx)/2-3), py((mn+mx)/2+6), py((mn+mx)/2-6)].map((y,i)=>(
          <line key={i} x1={pad.l} x2={W-pad.r} y1={y} y2={y} stroke="rgba(255,255,255,0.15)" strokeWidth="0.8" strokeDasharray="4,4"/>
        ))}
        <path d={makePath(CARRY_BUY,px,py)} fill="none" stroke="#34d399" strokeWidth="1.2" strokeDasharray="5,3" opacity="0.7"/>
        <path d={makePath(CARRY_SELL,px,py)} fill="none" stroke="#f87171" strokeWidth="1.2" strokeDasharray="5,3" opacity="0.7"/>
        <path d={makePath(SPREAD_TS,px,py)} fill="none" stroke="#38bdf8" strokeWidth="2" opacity="0.9"/>
        {[0,0.25,0.5,0.75,1].map(t=>{
          const v=(mn+rng*t).toFixed(0);
          return <text key={t} x={pad.l-4} y={pad.t+ih*(1-t)+3} textAnchor="end" fill="rgba(255,255,255,0.35)" fontSize="8">{v}</text>;
        })}
        {months.map((l,i)=>(
          <text key={i} x={px(i*step)} y={H-6} textAnchor="middle" fill="rgba(255,255,255,0.3)" fontSize="8">{l}</text>
        ))}
        {/* Right axis label */}
        <text x={W-4} y={pad.t} textAnchor="end" fill="rgba(255,255,255,0.25)" fontSize="7">carry</text>
        {[-8,-4,0,4,8].map((v,i)=>(
          <text key={i} x={W-4} y={pad.t+ih*0.5-v*5} textAnchor="start" fill="rgba(255,255,255,0.25)" fontSize="7">{v}</text>
        ))}
      </svg>
    );
  }

  function SeasonalChart() {
    const W=700,H=150,pad={t:16,b:30,l:36,r:12};
    const iw=W-pad.l-pad.r,ih=H-pad.t-pad.b;
    const mn=-0.15,mx=0.25,rng=mx-mn;
    const px=i=>pad.l+i*(iw/11);
    const py=v=>pad.t+ih-(((v-mn)/rng)*ih);
    const zeroY=py(0);
    const colors=['#38bdf8','#34d399',amber,'#a78bfa','#f87171'];
    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:'block'}}>
        <line x1={pad.l} x2={W-pad.r} y1={zeroY} y2={zeroY} stroke="rgba(255,255,255,0.15)" strokeWidth="1"/>
        {/* Highlight current month */}
        {(() => { const mi=MONTHS.indexOf(month); return mi>=0?<rect x={px(mi)-16} width={32} y={pad.t} height={ih} fill="rgba(139,92,246,0.12)" rx="2"/>:null; })()}
        {/* Year lines */}
        {SEASONAL.map((s,yi)=>(
          <path key={yi} d={s.map((v,i)=>`${i===0?'M':'L'}${px(i)},${py(v)}`).join(' ')}
            fill="none" stroke={colors[yi%5]} strokeWidth="1.2" opacity="0.6"/>
        ))}
        {/* Hist mean */}
        <path d={HIST_MEAN.map((v,i)=>`${i===0?'M':'L'}${px(i)},${py(v)}`).join(' ')}
          fill="none" stroke={amber} strokeWidth="2" opacity="0.9"/>
        {MONTHS.map((m,i)=>(
          <text key={i} x={px(i)} y={H-8} textAnchor="middle" fill={m===month?amber:"rgba(255,255,255,0.3)"} fontSize="8" fontWeight={m===month?700:400}>{m}</text>
        ))}
        {[mn,0,mx].map((v,i)=>(
          <text key={i} x={pad.l-4} y={py(v)+3} textAnchor="end" fill="rgba(255,255,255,0.35)" fontSize="8">{v>=0?'+':''}{v.toFixed(2)}</text>
        ))}
      </svg>
    );
  }

  return (
    <div style={{display:'flex',gap:'14px',alignItems:'flex-start'}}>
      {/* Sidebar */}
      <div style={{width:'140px',flexShrink:0,display:'flex',flexDirection:'column',gap:'10px'}}>
        <div style={{background:'var(--surface-panel)',border:'1px solid var(--border-strong)',borderRadius:'6px',padding:'10px 12px'}}>
          <div style={{font:'var(--type-label)',fontSize:'10px',color:amber,fontWeight:700,letterSpacing:'0.08em',marginBottom:'10px'}}>SPREAD EXPLORER</div>
          {[
            {label:'SPREAD TYPE', val:spreadType, set:setSpreadType, opts:SPREAD_TYPES},
            {label:'SEASONAL HIGHLIGHT MONTH', val:month, set:setMonth, opts:MONTHS},
            {label:'SEASONAL YEARS', val:years, set:setYears, opts:YEAR_OPTIONS},
          ].map(({label,val,set,opts})=>(
            <div key={label} style={{marginBottom:'10px'}}>
              <div style={{font:'var(--type-label)',fontSize:'8px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em',marginBottom:'4px'}}>{label}</div>
              <select value={val} onChange={e=>set(e.target.value)} style={{width:'100%',padding:'5px 6px',background:'var(--surface-input)',
                border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'10px',cursor:'pointer'}}>
                {opts.map(o=><option key={o}>{o}</option>)}
              </select>
            </div>
          ))}
        </div>
      </div>

      {/* Main content */}
      <div style={{flex:1,display:'flex',flexDirection:'column',gap:'12px',minWidth:0}}>
        {/* Daily spread stats */}
        <div style={{border:'1px solid var(--border-strong)',borderRadius:'6px',overflow:'hidden',background:'var(--surface-panel)'}}>
          <div style={{padding:'8px 12px',borderBottom:'1px solid var(--border-strong)',font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.07em'}}>Daily Spread Statistics</div>
          <div style={{padding:'10px 12px'}}>
            <svg width="100%" viewBox="0 0 700 80" style={{display:'block'}}>
              {/* Zero line */}
              <line x1={24} x2={676} y1={40} y2={40} stroke="rgba(255,255,255,0.15)" strokeWidth="1"/>
              {DAILY_SPREADS.map((s,i)=>{
                const x=24+i*(652/(DAILY_SPREADS.length-1));
                const barH=Math.abs(s.z)*18;
                const pos=s.z>=0;
                const color=pos?'rgba(52,211,153,0.75)':'rgba(239,68,68,0.75)';
                return (
                  <g key={i}>
                    <rect x={x-10} y={pos?40-barH:40} width={20} height={barH} fill={color} rx="1"/>
                    <text x={x} y={pos?40-barH-4:40+barH+10} textAnchor="middle" fill="rgba(255,255,255,0.6)" fontSize="7">{s.z.toFixed(1)}</text>
                    <text x={x} y={74} textAnchor="middle" fill="rgba(255,255,255,0.3)" fontSize="7" transform={`rotate(-35,${x},74)`}>{s.id}</text>
                  </g>
                );
              })}
            </svg>
          </div>
        </div>

        {/* Spread time series */}
        <div style={{border:'1px solid var(--border-strong)',borderRadius:'6px',overflow:'hidden',background:'var(--surface-panel)'}}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'8px 12px',borderBottom:'1px solid var(--border-strong)'}}>
            <span style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.07em'}}>Spread Time Series</span>
            <div style={{display:'flex',gap:'12px',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)'}}>
              {[['#38bdf8','Spread'],['#6b7280','FR007.IR'],['#34d399','CR BUY (3m,bp)'],['#f87171','CR SELL (3m,bp)']].map(([c,l])=>(
                <span key={l} style={{display:'flex',alignItems:'center',gap:'4px'}}>
                  <span style={{width:'12px',height:'2px',background:c,display:'inline-block',borderRadius:'1px'}}></span>{l}
                </span>
              ))}
            </div>
          </div>
          <div style={{padding:'4px 0 0',background:'var(--surface-panel)'}}>
            <div style={{padding:'4px 8px 0',font:'var(--type-data)',fontSize:'11px',color:'var(--text-primary)',fontWeight:600}}>SHI3MS9M.IR</div>
            <div style={{padding:'4px 8px 8px'}}><SpreadTimeSeries/></div>
          </div>
        </div>

        {/* Seasonal pattern */}
        <div style={{border:'1px solid var(--border-strong)',borderRadius:'6px',overflow:'hidden',background:'var(--surface-panel)'}}>
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',padding:'8px 12px',borderBottom:'1px solid var(--border-strong)'}}>
            <span style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.07em'}}>Seasonal Pattern</span>
            <div style={{display:'flex',gap:'10px',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)'}}>
              {['2022','2023','2024','2025','2026'].map((y,i)=>{
                const c=['#38bdf8','#34d399',amber,'#a78bfa','#f87171'][i];
                return <span key={y} style={{display:'flex',alignItems:'center',gap:'3px'}}><span style={{width:'12px',height:'2px',background:c,display:'inline-block'}}></span>{y}</span>;
              })}
              <span style={{display:'flex',alignItems:'center',gap:'3px'}}><span style={{width:'12px',height:'2px',background:amber,display:'inline-block'}}></span>Hist. Mean</span>
            </div>
          </div>
          <div style={{padding:'4px 8px 2px'}}><SeasonalChart/></div>

          {/* Monthly stats table */}
          <div style={{borderTop:'1px solid var(--border-strong)'}}>
            <table style={{width:'100%',borderCollapse:'collapse',font:'var(--type-data)',fontSize:'10px'}}>
              <thead>
                <tr style={{background:'var(--surface-panel)',borderBottom:'1px solid var(--border-strong)'}}>
                  {['Month','Dir','Cons%','AvgΔ','Obs','p-val'].map(h=>(
                    <th key={h} style={{padding:'5px 10px',textAlign:h==='Month'||h==='Dir'?'left':'right',
                      font:'var(--type-label)',fontSize:'8px',color:'var(--text-muted)',letterSpacing:'0.05em'}}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {MONTHLY_STATS.map((r,i)=>(
                  <tr key={i} style={{borderBottom:'1px solid rgba(255,255,255,0.04)',
                    background:r.highlight?'rgba(99,102,241,0.1)':i%2===0?'transparent':'rgba(255,255,255,0.015)'}}>
                    <td style={{padding:'4px 10px',color:r.highlight?'var(--accent-purple)':'var(--text-secondary)',fontWeight:r.highlight?600:400}}>{r.m}</td>
                    <td style={{padding:'4px 10px',color:r.dir==='↑'?'#34d399':r.dir==='↓'?'#f87171':'var(--text-muted)',fontWeight:700}}>{r.dir}</td>
                    <td style={{padding:'4px 10px',textAlign:'right',color:'var(--text-secondary)'}}>{r.cons}</td>
                    <td style={{padding:'4px 10px',textAlign:'right',color:'var(--text-secondary)'}}>{r.avg}</td>
                    <td style={{padding:'4px 10px',textAlign:'right',color:'var(--text-muted)'}}>{r.obs}</td>
                    <td style={{padding:'4px 10px',textAlign:'right',color:'var(--text-muted)'}}>{r.p}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{padding:'6px 10px',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)',borderTop:'1px solid rgba(255,255,255,0.04)'}}>
              * p&lt;0.10 ** p&lt;0.05 (one-sided binomial; no FDR correction applied)
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
window.AlphaSpread = AlphaSpread;
