// Summary > Tickets — trade tickets / order log
const _ns_st = window.AtlasNexusDesignSystem_988df3;

const TICKETS = [
  { id:'TKT-20260626-001', time:'00:12:44', book:'Alpha', spread:'CDBCGB-5y',    action:'BUY',  qty:500,  price:45.0,  status:'FILLED',  fill:45.0,  slippage:0.0,  pnl:+6.8  },
  { id:'TKT-20260626-002', time:'00:14:22', book:'Beta',  spread:'Repo7d-1y2y',  action:'BUY',  qty:300,  price:1.312, status:'FILLED',  fill:1.313, slippage:-0.1, pnl:+2.4  },
  { id:'TKT-20260626-003', time:'00:18:05', book:'Alpha', spread:'IRS-5s1s',     action:'BUY',  qty:200,  price:21.8,  status:'FILLED',  fill:21.9,  slippage:-0.1, pnl:+3.4  },
  { id:'TKT-20260626-004', time:'00:22:31', book:'Beta',  spread:'T',            action:'BUY',  qty:150,  price:1.831, status:'FILLED',  fill:1.831, slippage:0.0,  pnl:+3.2  },
  { id:'TKT-20260626-005', time:'00:28:14', book:'Alpha', spread:'BdSwap-2Y',    action:'SELL', qty:250,  price:25.9,  status:'FILLED',  fill:25.8,  slippage:-0.1, pnl:-2.2  },
  { id:'TKT-20260626-006', time:'00:31:58', book:'Beta',  spread:'CDBCGB-5y',    action:'BUY',  qty:400,  price:45.0,  status:'FILLED',  fill:45.1,  slippage:-0.1, pnl:+4.6  },
  { id:'TKT-20260626-007', time:'00:33:42', book:'Alpha', spread:'Repo7d-6m1y',  action:'BUY',  qty:350,  price:1.221, status:'PARTIAL', fill:1.222, slippage:-0.1, pnl:+1.1  },
  { id:'TKT-20260626-008', time:'00:34:01', book:'Beta',  spread:'260005.IB',    action:'BUY',  qty:100,  price:1.731, status:'PENDING', fill:null,  slippage:null, pnl:null  },
  { id:'TKT-20260626-009', time:'00:34:05', book:'Alpha', spread:'CGB-10s30s',   action:'BUY',  qty:180,  price:23.4,  status:'PENDING', fill:null,  slippage:null, pnl:null  },
  { id:'TKT-20260626-010', time:'00:34:08', book:'Beta',  spread:'TL2509',       action:'BUY',  qty:40,   price:118.94,status:'OPEN',   fill:null,  slippage:null, pnl:null  },
];

const STATUS_STYLE = {
  FILLED:  { bg:'rgba(52,211,153,0.12)', color:'#34d399' },
  PARTIAL: { bg:`rgba(224,162,60,0.15)`, color:'var(--accent-amber)' },
  PENDING: { bg:'rgba(59,130,246,0.12)', color:'var(--accent-blue)' },
  OPEN:    { bg:'rgba(255,255,255,0.06)', color:'var(--text-muted)' },
};

function SummaryTickets() {
  const { useState } = React;
  const [filter, setFilter] = useState('All');
  const accentCyan = 'var(--accent-cyan)';

  const rows = filter === 'All' ? TICKETS : TICKETS.filter(t => t.status === filter);
  const filled = TICKETS.filter(t => t.status === 'FILLED');
  const totalPnl = filled.reduce((s,t) => s+(t.pnl||0), 0);
  const totalSlip = filled.reduce((s,t) => s+(t.slippage||0), 0);

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'14px' }}>
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', flexWrap:'wrap', gap:'10px' }}>
        <div>
          <h1 style={{ margin:0, font:'var(--type-h1)', color:'var(--text-primary)' }}>Trade Tickets</h1>
          <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', marginTop:'3px' }}>Today · {TICKETS.length} orders · both books</div>
        </div>
        <div style={{ display:'flex', gap:'4px', background:'var(--surface-input)', padding:'3px', borderRadius:'5px', border:'1px solid var(--border-default)' }}>
          {['All','FILLED','PARTIAL','PENDING','OPEN'].map(f => (
            <button key={f} onClick={()=>setFilter(f)} style={{
              padding:'5px 10px', font:'var(--type-label)', fontSize:'10px', border:'none', borderRadius:'3px', cursor:'pointer',
              background: filter===f ? accentCyan : 'transparent',
              color: filter===f ? 'var(--navy-950)' : 'var(--text-muted)',
              transition:'all 0.15s',
            }}>{f}</button>
          ))}
        </div>
      </div>

      {/* Summary metrics */}
      <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit,minmax(120px,1fr))', gap:'10px' }}>
        {[
          { label:'Total Orders',  value: TICKETS.length },
          { label:'Filled',        value: TICKETS.filter(t=>t.status==='FILLED').length, positive:true },
          { label:'Pending/Open',  value: TICKETS.filter(t=>['PENDING','OPEN'].includes(t.status)).length },
          { label:'Filled PnL',    value: `${totalPnl>=0?'+':''}${totalPnl.toFixed(1)} bp`, positive:true },
          { label:'Total Slippage',value: `${totalSlip.toFixed(1)} bp`, negative:totalSlip<0 },
          { label:'Fill Rate',     value: `${(filled.length/TICKETS.length*100).toFixed(0)}%`, accent:true },
        ].map((s,i) => (
          <div key={i} style={{ background:'var(--surface-panel)', border:'1px solid var(--border-strong)', borderRadius:'6px', padding:'10px 14px' }}>
            <div style={{ font:'var(--type-meta)', color:'var(--text-muted)', marginBottom:'4px', fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.06em' }}>{s.label}</div>
            <div style={{ font:'var(--type-data)', fontSize:'16px', fontWeight:700,
              color: s.accent ? accentCyan : s.positive ? '#34d399' : s.negative ? '#f87171' : 'var(--text-primary)' }}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Tickets table */}
      <div style={{ overflowX:'auto', border:'1px solid var(--border-strong)', borderRadius:'6px' }}>
        <table style={{ width:'100%', borderCollapse:'collapse', font:'var(--type-data)', fontSize:'11px' }}>
          <thead>
            <tr style={{ background:'var(--surface-panel)', borderBottom:'1px solid var(--border-strong)' }}>
              {['Ticket ID','Time','Book','Spread / Instrument','Action','Qty','Price','Status','Fill','Slippage (bp)','PnL (bp)'].map(h => (
                <th key={h} style={{ padding:'7px 10px', textAlign:['Ticket ID','Time','Book','Spread / Instrument','Action','Status'].includes(h)?'left':'right',
                  font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', letterSpacing:'0.05em', whiteSpace:'nowrap' }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r,i) => {
              const ss = STATUS_STYLE[r.status] || STATUS_STYLE.OPEN;
              return (
                <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.04)', background:i%2===0?'transparent':'rgba(255,255,255,0.015)' }}>
                  <td style={{ padding:'5px 10px', color: accentCyan, fontWeight:500, fontSize:'10px', whiteSpace:'nowrap' }}>{r.id}</td>
                  <td style={{ padding:'5px 10px', color:'var(--text-muted)', fontSize:'10px' }}>{r.time}</td>
                  <td style={{ padding:'5px 10px' }}>
                    <span style={{ padding:'2px 6px', borderRadius:'3px', fontSize:'9px', fontWeight:600,
                      background: r.book==='Alpha'?'rgba(224,162,60,0.12)':'rgba(59,130,246,0.12)',
                      color: r.book==='Alpha'?'var(--accent-amber)':'var(--accent-blue)' }}>{r.book}</span>
                  </td>
                  <td style={{ padding:'5px 10px', color:'var(--text-primary)', fontWeight:500 }}>{r.spread}</td>
                  <td style={{ padding:'5px 10px' }}>
                    <span style={{ padding:'2px 6px', borderRadius:'3px', fontSize:'9px', fontWeight:700,
                      background:r.action==='BUY'?'rgba(52,211,153,0.12)':'rgba(239,68,68,0.12)',
                      color:r.action==='BUY'?'#34d399':'#f87171' }}>{r.action}</span>
                  </td>
                  <td style={{ padding:'5px 10px', textAlign:'right', color:'var(--text-secondary)' }}>{r.qty.toLocaleString()}</td>
                  <td style={{ padding:'5px 10px', textAlign:'right', color:'var(--text-primary)' }}>{r.price}</td>
                  <td style={{ padding:'5px 10px' }}>
                    <span style={{ padding:'2px 7px', borderRadius:'3px', fontSize:'9px', fontWeight:700, background:ss.bg, color:ss.color }}>{r.status}</span>
                  </td>
                  <td style={{ padding:'5px 10px', textAlign:'right', color: r.fill!=null?'var(--text-primary)':'var(--text-muted)' }}>{r.fill??'—'}</td>
                  <td style={{ padding:'5px 10px', textAlign:'right', color: r.slippage!=null?(r.slippage<0?'#f87171':'#34d399'):'var(--text-muted)' }}>{r.slippage!=null?r.slippage.toFixed(1):'—'}</td>
                  <td style={{ padding:'5px 10px', textAlign:'right', color: r.pnl!=null?(r.pnl>=0?'#34d399':'#f87171'):'var(--text-muted)', fontWeight:r.pnl!=null?600:400 }}>{r.pnl!=null?`${r.pnl>=0?'+':''}${r.pnl.toFixed(1)}`:'—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
window.SummaryTickets = SummaryTickets;
