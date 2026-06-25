// Beta Book > Factor — Factor Explorer + Historical Performance chart
const _ns_bfact = window.AtlasNexusDesignSystem_988df3;

const ASSET_CLASSES = ['Rates','FX','Equity','Commodity'];
const REGIONS = ['China','US','Europe','Global'];
const FACTOR_OPTIONS = ['Level (IRDL)','Slope (IRSL)','Curvature (IRCV)','FX Spot (FXDL)','Commodity (CMDL)','Equity (EQDL)'];
const PERIODS = ['1M','3M','6M','YTD','1Y','3Y','5Y','All'];

// Mock time-series data for 3 factors over 6M
function genSeries(base, amp, n=180) {
  let v=base, arr=[];
  for(let i=0;i<n;i++){v+=(Math.random()-0.5)*amp*0.04; arr.push(Math.max(0,v));}
  return arr;
}
const IRDL = genSeries(1.6, 0.08, 180);
const IRSL = genSeries(0.46, 0.06, 180);
const IRCV = genSeries(0.06, 0.02, 180);

function BetaFactor() {
  const { useState } = React;
  const [assetClass, setAssetClass] = useState('Rates');
  const [region, setRegion] = useState('China');
  const [factors, setFactors] = useState(['Level (IRDL)','Slope (IRSL)','Curvature (IRCV)']);
  const [period, setPeriod] = useState('6M');
  const accentBlue = 'var(--accent-blue)';

  const W=700, H=280;
  const allVals=[...IRDL,...IRSL,...IRCV];
  const mn=0, mx=Math.max(...allVals)*1.1, rng=mx-mn;
  function px(v,i,n){ return { x:(i/(n-1))*(W-50)+40, y:H-30-((v-mn)/rng)*(H-50) }; }
  function path(arr){ return arr.map((v,i)=>{ const p=px(v,i,arr.length); return `${i===0?'M':'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`; }).join(' '); }

  const LINES = [
    { data:IRDL, color:'#818cf8', label:'IRDL.CN' },
    { data:IRSL, color:'#f87171', label:'IRSL.CN' },
    { data:IRCV, color:'#34d399', label:'IRCV.CN' },
  ];

  const xLabels = ['Jan 2026','Feb 2026','Mar 2026','Apr 2026','May 2026','Jun 2026'];

  const Dropdown = ({ value, options, onChange }) => (
    <div style={{ position:'relative' }}>
      <select value={value} onChange={e=>onChange(e.target.value)} style={{
        appearance:'none', width:'100%', background:'var(--surface-input)',
        border:'1px solid var(--border-default)', borderRadius:'4px',
        padding:'6px 24px 6px 8px', font:'var(--type-data)', fontSize:'11px',
        color:'var(--text-primary)', cursor:'pointer',
      }}>
        {options.map(o=><option key={o}>{o}</option>)}
      </select>
      <span style={{ position:'absolute', right:'7px', top:'50%', transform:'translateY(-50%)', pointerEvents:'none', color:'var(--text-muted)', fontSize:'10px' }}>×▾</span>
    </div>
  );

  return (
    <div style={{ display:'flex', gap:'16px', alignItems:'start' }}>

      {/* LEFT SIDEBAR */}
      <div style={{ width:'200px', flexShrink:0, background:'var(--surface-panel)', border:'1px solid var(--border-strong)', borderRadius:'8px', padding:'14px 14px', display:'flex', flexDirection:'column', gap:'14px' }}>
        <div style={{ font:'var(--type-label)', color:'var(--text-primary)', fontSize:'11px', fontWeight:700, letterSpacing:'0.08em', textTransform:'uppercase' }}>Factor Explorer</div>
        <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'10px', lineHeight:'1.5' }}>
          Browse the historical level of any risk factor. Select asset class → region → factor types.
        </div>

        <div>
          <div style={{ font:'var(--type-label)', color:accentBlue, fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'5px' }}>Asset Class</div>
          <Dropdown value={assetClass} options={ASSET_CLASSES} onChange={setAssetClass} />
        </div>
        <div>
          <div style={{ font:'var(--type-label)', color:accentBlue, fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'5px' }}>Region / Type</div>
          <Dropdown value={region} options={REGIONS} onChange={setRegion} />
        </div>
        <div>
          <div style={{ font:'var(--type-label)', color:accentBlue, fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'5px' }}>Factor(s)</div>
          <div style={{ background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'6px 8px', font:'var(--type-data)', fontSize:'10px', color:'var(--text-primary)', cursor:'pointer', display:'flex', justifyContent:'space-between' }}>
            <span>Level (IRDL) - ...</span>
            <span style={{ color:'var(--text-muted)' }}>{factors.length} selected ×▾</span>
          </div>
        </div>

        <div style={{ borderTop:'1px solid var(--border-default)', paddingTop:'10px' }}>
          <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'9px', lineHeight:'1.6' }}>
            Factor naming convention:<br/>
            IRDL = Level · IRSL = Slope · IRCV = Curvature<br/>
            FXDL = FX spot · CMDL = Commodity · EQDL = Equity
          </div>
        </div>
      </div>

      {/* MAIN CHART AREA */}
      <div style={{ flex:1, minWidth:0, display:'flex', flexDirection:'column', gap:'12px' }}>
        <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.08em' }}>Historical Performance</div>

        {/* Period buttons + toolbar */}
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center' }}>
          <div style={{ display:'flex', gap:'4px' }}>
            {PERIODS.map(p=>(
              <button key={p} onClick={()=>setPeriod(p)} style={{
                padding:'4px 10px', font:'var(--type-label)', fontSize:'10px', border:'none', borderRadius:'4px', cursor:'pointer',
                background: period===p ? accentBlue : 'rgba(255,255,255,0.06)',
                color: period===p ? '#fff' : 'var(--text-muted)', transition:'all 0.15s',
              }}>{p}</button>
            ))}
          </div>
          {/* Toolbar icons */}
          <div style={{ display:'flex', gap:'6px' }}>
            {['⤡','🔍','+','□','✕','⌂','▦'].map((ic,i)=>(
              <div key={i} style={{ width:'24px', height:'24px', borderRadius:'3px', background:'rgba(255,255,255,0.06)', display:'flex', alignItems:'center', justifyContent:'center', cursor:'pointer', fontSize:'11px', color:'var(--text-muted)' }}>{ic}</div>
            ))}
          </div>
        </div>

        {/* Legend */}
        <div style={{ display:'flex', gap:'20px', justifyContent:'flex-end' }}>
          {LINES.map(l=>(
            <div key={l.label} style={{ display:'flex', alignItems:'center', gap:'6px', font:'var(--type-meta)', color:'var(--text-secondary)', fontSize:'10px' }}>
              <div style={{ width:'24px', height:'2px', background:l.color, borderRadius:'1px' }}></div>
              {l.label}
            </div>
          ))}
        </div>

        {/* Chart */}
        <div style={{ background:'var(--surface-panel)', border:'1px solid var(--border-strong)', borderRadius:'6px', padding:'10px' }}>
          <svg viewBox={`0 0 ${W} ${H}`} style={{ width:'100%', height:'auto' }} preserveAspectRatio="xMidYMid meet">
            {/* Grid */}
            {[0,0.2,0.4,0.6,0.8,1.0,1.2,1.4,1.6].map((v,i)=>{
              const yy = H-30-((v-mn)/rng)*(H-50);
              return (
                <g key={i}>
                  <line x1="40" y1={yy} x2={W-10} y2={yy} stroke="rgba(100,140,200,0.1)" strokeWidth="0.8"/>
                  <text x="35" y={yy+4} textAnchor="end" fontSize="9" fill="rgba(150,180,220,0.6)">{v.toFixed(1)}</text>
                </g>
              );
            })}
            {/* X labels */}
            {xLabels.map((l,i)=>(
              <text key={i} x={40+(i/(xLabels.length-1))*(W-50)} y={H-8} textAnchor="middle" fontSize="9" fill="rgba(150,180,220,0.6)">{l}</text>
            ))}
            <text x={W/2} y={H+2} textAnchor="middle" fontSize="9" fill="rgba(150,180,220,0.5)">Date</text>
            <text x="12" y={H/2} textAnchor="middle" fontSize="9" fill="rgba(150,180,220,0.5)" transform={`rotate(-90,12,${H/2})`}>Value</text>
            {/* Lines */}
            {LINES.map(l=>(
              <path key={l.label} d={path(l.data)} stroke={l.color} strokeWidth="1.5" fill="none" opacity="0.9"/>
            ))}
          </svg>
        </div>
      </div>
    </div>
  );
}
window.BetaFactor = BetaFactor;
