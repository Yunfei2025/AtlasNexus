// Beta Book > Bond — Bond Trading Signals (Z-Score) by maturity bucket
const _ns_bbond = window.AtlasNexusDesignSystem_988df3;

const BOND_TYPES = ['Treasury Bond (TBond)', 'CDB Bond', 'Policy Bank', 'Corp AAA'];

const BUCKETS = [
  {
    label:'0-1Y', ttm:'(0, 1) years', count:2, avgZ:-1.42,
    sell:[
      { name:'210011.IB', mid:1.139, cr:-38.91, ttm:'0.16Y', z:-1.65 },
      { name:'250012.IB', mid:1.156, cr:-9.34,  ttm:'1.00Y', z:-1.19 },
    ],
    buy:[
      { name:'250012.IB', mid:1.156, cr:-9.34,  ttm:'1.00Y', z:-1.19 },
      { name:'210011.IB', mid:1.139, cr:-38.91, ttm:'0.16Y', z:-1.65 },
    ],
  },
  {
    label:'1-3Y', ttm:'(1, 3) years', count:22, avgZ:+0.16,
    sell:[
      { name:'220016.IB', mid:1.137, cr:-11.71, ttm:'1.11Y', z:-3.90 },
      { name:'220022.IB', mid:1.154, cr:-9.61,  ttm:'1.33Y', z:-2.61 },
      { name:'230002.IB', mid:1.148, cr:-8.07,  ttm:'1.58Y', z:-1.32 },
      { name:'240016.IB', mid:1.181, cr:-8.84,  ttm:'1.16Y', z:-1.17 },
      { name:'250017.IB', mid:1.230, cr:-6.91,  ttm:'1.25Y', z:-0.99 },
    ],
    buy:[
      { name:'260004.IB', mid:1.278, cr:1.31,   ttm:'2.70Y', z:2.49  },
      { name:'250023.IB', mid:1.259, cr:-0.15,  ttm:'2.44Y', z:2.20  },
      { name:'230015.IB', mid:1.187, cr:-3.42,  ttm:'2.08Y', z:1.34  },
      { name:'230022.IB', mid:1.202, cr:-2.20,  ttm:'2.33Y', z:1.15  },
      { name:'250010.IB', mid:1.179, cr:-4.14,  ttm:'1.94Y', z:1.15  },
    ],
  },
  {
    label:'3-5Y', ttm:'(3, 5) years', count:14, avgZ:+0.55,
    sell:[
      { name:'250014.IB', mid:1.392, cr:7.48,  ttm:'4.11Y', z:-0.23 },
      { name:'260008.IB', mid:1.499, cr:10.16, ttm:'4.83Y', z:-0.04 },
      { name:'230006.IB', mid:1.307, cr:5.05,  ttm:'3.77Y', z:0.14  },
      { name:'220027.IB', mid:1.295, cr:4.16,  ttm:'3.50Y', z:0.38  },
      { name:'220021.IB', mid:1.298, cr:3.65,  ttm:'3.28Y', z:0.42  },
    ],
    buy:[
      { name:'240014.IB', mid:1.301, cr:3.63,  ttm:'3.08Y', z:1.12  },
      { name:'230019.IB', mid:1.387, cr:8.58,  ttm:'4.25Y', z:1.06  },
      { name:'240020.IB', mid:1.330, cr:4.84,  ttm:'3.33Y', z:0.99  },
      { name:'230014.IB', mid:1.362, cr:7.45,  ttm:'4.02Y', z:0.89  },
      { name:'250003.IB', mid:1.347, cr:6.09,  ttm:'3.61Y', z:0.70  },
    ],
  },
  {
    label:'5-7Y', ttm:'(5, 7) years', count:15, avgZ:-0.11,
    sell:[
      { name:'230012.IB', mid:1.586, cr:12.71, ttm:'6.94Y', z:-0.92 },
      { name:'220025.IB', mid:1.538, cr:12.34, ttm:'6.42Y', z:-0.72 },
      { name:'250018.IB', mid:1.568, cr:12.73, ttm:'6.25Y', z:-0.68 },
    ],
    buy:[
      { name:'230008.IB', mid:1.601, cr:13.41, ttm:'6.80Y', z:0.54  },
      { name:'240009.IB', mid:1.572, cr:11.88, ttm:'5.94Y', z:0.41  },
    ],
  },
  {
    label:'7-10Y', ttm:'(7, 10) years', count:12, avgZ:+0.37,
    sell:[
      { name:'230018.IB', mid:1.601, cr:12.65, ttm:'7.19Y', z:-0.84 },
      { name:'230026.IB', mid:1.613, cr:12.69, ttm:'7.44Y', z:-0.84 },
      { name:'240011.IB', mid:1.652, cr:12.81, ttm:'7.94Y', z:-0.80 },
    ],
    buy:[
      { name:'260005.IB', mid:1.731, cr:14.20, ttm:'9.22Y', z:1.23  },
      { name:'250022.IB', mid:1.712, cr:13.88, ttm:'9.08Y', z:0.97  },
    ],
  },
];

function BetaBond() {
  const { useState } = React;
  const [bondType, setBondType] = useState('Treasury Bond (TBond)');
  const [ts, setTs] = useState('06:57:28');

  function BucketTable({ rows, type }) {
    const isSell = type === 'sell';
    const bg = isSell ? 'rgba(239,68,68,0.12)' : 'rgba(52,211,153,0.1)';
    const badgeBg = isSell ? '#b91c1c' : '#166534';
    const badgeColor = '#fff';
    const zColor = isSell ? '#f87171' : '#34d399';
    return (
      <div style={{ marginBottom:'10px' }}>
        <div style={{ display:'inline-block', padding:'2px 10px', borderRadius:'12px', background:badgeBg, color:badgeColor, font:'var(--type-label)', fontSize:'9px', fontWeight:700, letterSpacing:'0.06em', marginBottom:'6px' }}>
          {isSell ? 'SELL (LOW Z)' : 'BUY (HIGH Z)'}
        </div>
        <table style={{ width:'100%', borderCollapse:'collapse', font:'var(--type-data)', fontSize:'10px' }}>
          <thead>
            <tr style={{ borderBottom:'1px solid rgba(255,255,255,0.08)' }}>
              {['NAME','MID PRICE','C+R,3M','TTM','Z-SCORE'].map(h=>(
                <th key={h} style={{ padding:'3px 6px', textAlign: h==='NAME'?'left':'right', font:'var(--type-label)', fontSize:'8px', color:'var(--text-muted)', letterSpacing:'0.05em' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r,i)=>(
              <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding:'4px 6px', color:'var(--text-primary)', fontWeight:500 }}>{r.name}</td>
                <td style={{ padding:'4px 6px', textAlign:'right', color:'var(--text-secondary)' }}>{r.mid.toFixed(3)}</td>
                <td style={{ padding:'4px 6px', textAlign:'right', color: r.cr>=0?'#34d399':'#f87171' }}>{r.cr.toFixed(2)}</td>
                <td style={{ padding:'4px 6px', textAlign:'right', color:'var(--text-muted)' }}>{r.ttm}</td>
                <td style={{ padding:'4px 6px', textAlign:'right', color:zColor, fontWeight:700,
                  background: isSell ? `rgba(239,68,68,${Math.min(Math.abs(r.z)/4,1)*0.3})` : `rgba(52,211,153,${Math.min(Math.abs(r.z)/3,1)*0.25})` }}>
                  {r.z.toFixed(2)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  function BucketCard({ b }) {
    const avgPos = b.avgZ >= 0;
    return (
      <div style={{ background:'var(--surface-panel)', border:'1px solid var(--border-strong)', borderRadius:'8px', padding:'14px 14px' }}>
        <div style={{ display:'flex', justifyContent:'space-between', alignItems:'baseline', marginBottom:'3px' }}>
          <span style={{ font:'var(--type-h3)', color:'var(--text-primary)', fontSize:'14px', fontWeight:700 }}>{b.label}</span>
        </div>
        <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'9px', marginBottom:'8px' }}>TTM in {b.ttm}</div>
        <div style={{ display:'flex', gap:'8px', alignItems:'center', marginBottom:'12px' }}>
          <span style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'10px' }}>{b.count} bonds</span>
          <span style={{ padding:'2px 8px', borderRadius:'10px', font:'var(--type-label)', fontSize:'9px', fontWeight:700,
            background: avgPos ? 'rgba(52,211,153,0.18)' : 'rgba(239,68,68,0.18)',
            color: avgPos ? '#34d399' : '#f87171' }}>
            Avg Z {b.avgZ >= 0 ? '+' : ''}{b.avgZ.toFixed(2)}
          </span>
        </div>
        <BucketTable rows={b.sell} type="sell" />
        <BucketTable rows={b.buy} type="buy" />
      </div>
    );
  }

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'14px' }}>
      {/* Header */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'flex-start', flexWrap:'wrap', gap:'12px' }}>
        <div>
          <h1 style={{ margin:'0 0 4px', font:'var(--type-h1)', color:'var(--text-primary)', fontSize:'16px' }}>Bond Trading Signals (Z-Score)</h1>
          <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'11px' }}>Realtime relative-value signals by maturity bucket. Labels are inverted per request: low Z shows SELL and high Z shows BUY.</div>
        </div>
        <div style={{ display:'flex', gap:'10px', alignItems:'center', flexShrink:0 }}>
          <div>
            <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.06em', marginBottom:'4px' }}>Bond Type</div>
            <div style={{ position:'relative' }}>
              <select value={bondType} onChange={e=>setBondType(e.target.value)} style={{
                appearance:'none', background:'var(--surface-input)', border:'1px solid var(--border-default)',
                borderRadius:'5px', padding:'7px 28px 7px 10px', font:'var(--type-data)', fontSize:'11px',
                color:'var(--text-primary)', cursor:'pointer', minWidth:'180px',
              }}>
                {BOND_TYPES.map(t=><option key={t}>{t}</option>)}
              </select>
              <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ position:'absolute', right:'8px', top:'50%', transform:'translateY(-50%)', pointerEvents:'none' }}>
                <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
            </div>
          </div>
          <button onClick={()=>{const n=new Date();setTs(`${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')}:${String(n.getSeconds()).padStart(2,'0')}`);}} style={{
            marginTop:'16px', padding:'7px 14px', font:'var(--type-label)', fontSize:'11px', fontWeight:600,
            background:'var(--accent-blue)', color:'#fff', border:'none', borderRadius:'5px', cursor:'pointer',
          }}>Refresh Data</button>
        </div>
      </div>

      {/* Meta row */}
      <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', fontSize:'10px' }}>
        Loaded {bondType} · {BUCKETS.reduce((s,b)=>s+b.count,0)} live rows · 2026-06-26 {ts}
      </div>

      {/* Bucket grid */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(3,1fr)', gap:'14px' }}>
        {BUCKETS.map((b,i)=><BucketCard key={i} b={b} />)}
      </div>
    </div>
  );
}
window.BetaBond = BetaBond;
