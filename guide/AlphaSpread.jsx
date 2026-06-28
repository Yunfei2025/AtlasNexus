// Alpha Book > Spread — consistent with Candidates/Portfolio pattern
const _ns_as = window.AtlasNexusDesignSystem_988df3;

const SPREAD_TYPES = ['Curve & Cross-Ass...','Swap Spread','Tenor Spread','Bond Swap','IRS Curve'];
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

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
  const amber = 'var(--accent-amber)';

  // Chart helpers
  function makePath(data, px, py) { return data.map((v,i)=>`${i===0?'M':'L'}${px(i)},${py(v)}`).join(' '); }

  function SpreadTimeSeries() {
    const W=700,H=180,pad={t:12,b:24,l:36,r:12};
    const iw=W-pad.l-pad.r,ih=H-pad.t-pad.b;
    const allVals=[...SPREAD_TS,...CARRY_BUY,...CARRY_SELL,...UPPER_BAND,...LOWER_BAND];
    const mn=Math.min(...allVals)-1,mx=Math.max(...allVals)+1,rng=mx-mn||1;
    const px=i=>pad.l+i*(iw/(N-1));
    const py=v=>pad.t+ih-(((v-mn)/rng)*ih);
    const months=['Jul 25','Sep 25','Nov 25','Jan 26','Mar 26','May 26'];
    const step=Math.floor(N/5);
    return (
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:'block'}}>
        {[0,0.25,0.5,0.75,1].map(t=>(
          <line key={t} x1={pad.l} x2={W-pad.r} y1={pad.t+ih*t} y2={pad.t+ih*t} stroke="rgba(255,255,255,0.06)" strokeWidth="1"/>
        ))}
        <polygon points={[...UPPER_BAND.map((v,i)=>`${px(i)},${py(v)}`), ...[...LOWER_BAND].reverse().map((v,i,a)=>`${px(a.length-1-i)},${py(v)}`)].join(' ')} fill="rgba(100,160,220,0.12)"/>
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
      </svg>
    );
  }

  function CardHeader({ title, id, badge }) {
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
        <h1 style={{margin:'0 0 3px',font:'var(--type-h1)',color:'var(--text-primary)'}}>Spread Analysis</h1>
        <div style={{font:'var(--type-meta)',color:'var(--text-muted)'}}>Time series, seasonal patterns, and daily statistics</div>
      </div>

      {/* Top row: Controls (left) + Daily Statistics selector (right) */}
      <div style={{display:'flex',gap:'12px',alignItems:'flex-start'}}>
        {/* Controls card — narrow, fixed width */}
        <div style={{width:'220px',flexShrink:0,border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
          <CardHeader title="Controls" />
          <div style={{padding:'12px 14px',display:'flex',flexDirection:'column',gap:'12px'}}>
            <div style={{display:'flex',flexDirection:'column',gap:'4px'}}>
              <div style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em'}}>Spread Type</div>
              <select value={spreadType} onChange={e=>setSpreadType(e.target.value)} style={{padding:'6px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'10px',cursor:'pointer'}}>
                {SPREAD_TYPES.map(o=><option key={o}>{o}</option>)}
              </select>
            </div>
            <div style={{display:'flex',flexDirection:'column',gap:'4px'}}>
              <div style={{font:'var(--type-label)',fontSize:'9px',color:'var(--text-muted)',textTransform:'uppercase',letterSpacing:'0.06em'}}>Highlight Month</div>
              <select value={month} onChange={e=>setMonth(e.target.value)} style={{padding:'6px 8px',background:'var(--surface-input)',border:'1px solid var(--border-default)',borderRadius:'4px',color:'var(--text-primary)',font:'var(--type-data)',fontSize:'10px',cursor:'pointer'}}>
                {MONTHS.map(o=><option key={o}>{o}</option>)}
              </select>
            </div>
            <button style={{padding:'6px 12px',background:amber,color:'var(--navy-950)',border:'none',borderRadius:'4px',font:'var(--type-label)',fontSize:'10px',fontWeight:700,cursor:'pointer',width:'100%'}}>↻ Refresh</button>
            <div style={{font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)',marginTop:'4px'}}>Updated: 07:46:05</div>
          </div>
        </div>

        {/* Daily Spread Statistics — flex 1 */}
        <div style={{flex:1,minWidth:0,border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
          <CardHeader title="Daily Spread Statistics" badge="Z-score distribution · pick spreads below" />
          <div style={{padding:'12px 16px'}}>
            <svg width="100%" viewBox="0 0 700 80" style={{display:'block'}}>
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
      </div>

      {/* Time series chart */}
      <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
        <CardHeader title="Spread Time Series" badge="SHI3MS9M.IR" />
        <div style={{padding:'12px 16px',display:'flex',gap:'12px',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)',borderBottom:'1px solid var(--border-strong)'}}>
          {[['#38bdf8','Spread'],['#34d399','Carry BUY (3m,bp)'],['#f87171','Carry SELL (3m,bp)'],['rgba(100,160,220,0.3)','±Bollinger Band']].map(([c,l])=>(
            <span key={l} style={{display:'flex',alignItems:'center',gap:'4px'}}>
              <span style={{width:'12px',height:'2px',background:c,display:'inline-block',borderRadius:'1px'}}></span>{l}
            </span>
          ))}
        </div>
        <div style={{padding:'12px 16px'}}><SpreadTimeSeries/></div>
      </div>

      {/* Monthly statistics table */}
      <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
        <CardHeader title="Monthly Statistics" badge="Historical directional bias and consistency" />
        <div style={{overflowX:'auto'}}>
          <table style={{width:'100%',borderCollapse:'collapse',font:'var(--type-data)',fontSize:'10px'}}>
            <thead>
              <tr style={{background:'var(--surface-panel)',borderBottom:'1px solid var(--border-strong)'}}>
                {['Month','Direction','Consistency','Avg Δ','Observations','p-value'].map(h=>(
                  <th key={h} style={{padding:'8px 12px',textAlign:h==='Month'||h==='Direction'?'left':'right',font:'var(--type-label)',fontSize:'8px',color:'var(--text-muted)',letterSpacing:'0.05em'}}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {MONTHLY_STATS.map((r,i)=>(
                <tr key={i} style={{borderBottom:'1px solid rgba(255,255,255,0.04)',background:r.highlight?'rgba(99,102,241,0.1)':i%2===0?'transparent':'rgba(255,255,255,0.015)'}}>
                  <td style={{padding:'6px 12px',color:r.highlight?'var(--accent-purple)':'var(--text-secondary)',fontWeight:r.highlight?600:400}}>{r.m}</td>
                  <td style={{padding:'6px 12px',color:r.dir==='↑'?'#34d399':r.dir==='↓'?'#f87171':'var(--text-muted)',fontWeight:700}}>{r.dir}</td>
                  <td style={{padding:'6px 12px',textAlign:'right',color:'var(--text-secondary)'}}>{r.cons}</td>
                  <td style={{padding:'6px 12px',textAlign:'right',color:'var(--text-secondary)'}}>{r.avg}</td>
                  <td style={{padding:'6px 12px',textAlign:'right',color:'var(--text-muted)'}}>{r.obs}</td>
                  <td style={{padding:'6px 12px',textAlign:'right',color:'var(--text-muted)'}}>{r.p}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div style={{padding:'8px 12px',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)',background:'rgba(255,255,255,0.02)',borderTop:'1px solid var(--border-strong)'}}>
          * p&lt;0.10 ** p&lt;0.05 (one-sided binomial; no FDR correction applied)
        </div>
      </div>
    </div>
  );
}
window.AlphaSpread = AlphaSpread;
