// Market > Pricer — bond pricer table with z-score heatmap
const _ns_mp = window.AtlasNexusDesignSystem_988df3;

const INSTRUMENT_TYPES = ['TBond (Treasury)', 'CDB', 'Policy Bank', 'Corp'];
const SUBTYPE_TERMS = ['1 – 3 Y', '3 – 5 Y', '5 – 10 Y', '10 – 30 Y', 'All'];

const PRICER_ROWS = [
  { ticker:'210013.IB', cpn:2.91, ptmy:2.329, yld:1.155, z:0.2,   stat:'YES', hl:9.1,  vr:1.03, cls:1.1514, bid:1.17,  ofr:1.135, mid:1.1525, dyld:-0.25, carry:-8.38, roll:4.44,  cr:-3.94 },
  { ticker:'240008.IB', cpn:2.62, ptmy:1.83,  yld:1.16,  z:-0.34, stat:'YES', hl:7,    vr:0.99, cls:1.1593, bid:1.17,  ofr:1.1475,mid:1.1587, dyld:-0.13, carry:-8.25, roll:1.99,  cr:-6.26 },
  { ticker:'240001.IB', cpn:2.37, ptmy:2.584, yld:1.256, z:1.03,  stat:'NO',  hl:null, vr:0.9,  cls:1.2338, bid:1.2788,ofr:1.2288,mid:1.2538, dyld:-0.22, carry:-5.85, roll:5.56,  cr:-0.29 },
  { ticker:'250023.IB', cpn:1.4,  ptmy:2.444, yld:1.29,  z:2.2,   stat:'NO',  hl:null, vr:0.98, cls:1.2592, bid:1.3075,ofr:1.28,  mid:1.2938, dyld:0.38,  carry:-5,    roll:4.85,  cr:-0.15 },
  { ticker:'250010.IB', cpn:1.46, ptmy:1.94,  yld:1.2247,z:1.15,  stat:'NO',  hl:null, vr:0.72, cls:1.1786, bid:1.245, ofr:1.2025,mid:1.2237, dyld:-0.1,  carry:-6.63, roll:2.49,  cr:-4.14 },
  { ticker:'220012.IB', cpn:2.75, ptmy:2.997, yld:1.27,  z:0.97,  stat:'NO',  hl:null, vr:1.03, cls:1.2542, bid:1.2875,ofr:1.26,  mid:1.2738, dyld:0.38,  carry:-5.5,  roll:7.32,  cr:1.82  },
  { ticker:'250017.IB', cpn:1.44, ptmy:1.249, yld:1.24,  z:-0.99, stat:'NO',  hl:null, vr:0.95, cls:1.2303, bid:1.2525,ofr:1.225, mid:1.2388, dyld:-0.12, carry:-6.25, roll:-0.66, cr:-6.91 },
  { ticker:'250015.IB', cpn:1.42, ptmy:2.164, yld:1.29,  z:1.07,  stat:'YES', hl:5.9,  vr:0.98, cls:1.2552, bid:1.3,   ofr:1.2583,mid:1.2792, dyld:-1.08, carry:-5,    roll:3.59,  cr:-1.41 },
  { ticker:'240008.IB', cpn:2.05, ptmy:2.83,  yld:1.3,   z:0.98,  stat:'NO',  hl:null, vr:0.81, cls:1.2674, bid:1.314, ofr:1.264, mid:1.289,  dyld:-1.1,  carry:-4.75, roll:6.57,  cr:1.82  },
  { ticker:'260006.IB', cpn:1.29, ptmy:1.745, yld:1.267, z:-0.07, stat:'YES', hl:6.6,  vr:0.29, cls:1.2849, bid:1.272, ofr:1.2575,mid:1.2648, dyld:-0.22, carry:-5.58, roll:1.55,  cr:-4.03 },
  { ticker:'220016.IB', cpn:2.5,  ptmy:1.107, yld:1.07,  z:-3.9,  stat:'NO',  hl:null, vr:1.01, cls:1.1366, bid:1.1025,ofr:1.0475,mid:1.075,  dyld:0.5,   carry:-10.5, roll:-1.21, cr:-11.71},
  { ticker:'230002.IB', cpn:2.64, ptmy:1.584, yld:1.135, z:-1.32, stat:'YES', hl:10.2, vr:1,    cls:1.1485, bid:1.145, ofr:1.1225,mid:1.1338, dyld:-0.12, carry:-8.88, roll:0.8,   cr:-8.08 },
  { ticker:'230015.IB', cpn:2.4,  ptmy:2.079, yld:1.225, z:1.34,  stat:'NO',  hl:null, vr:0.98, cls:1.187,  bid:1.235, ofr:1.2125,mid:1.2237, dyld:-0.13, carry:-6.62, roll:3.21,  cr:-3.41 },
  { ticker:'260004.IB', cpn:1.32, ptmy:2.696, yld:1.305, z:2.49,  stat:'YES', hl:2.5,  vr:0.86, cls:1.2777, bid:1.31,  ofr:1.295, mid:1.3025, dyld:-0.25, carry:-4.63, roll:5.93,  cr:1.3   },
  { ticker:'220022.IB', cpn:2.44, ptmy:1.332, yld:1.1187,z:-2.61, stat:'YES', hl:8.2,  vr:0.99, cls:1.1535, bid:1.1425,ofr:1.0975,mid:1.12,   dyld:0.13,  carry:-9.28, roll:-0.33, cr:-9.61 },
  { ticker:'250024.IB', cpn:1.36, ptmy:1.499, yld:1.25,  z:-0.22, stat:'NO',  hl:null, vr:1.09, cls:1.2353, bid:1.26,  ofr:1.2375,mid:1.2488, dyld:-0.12, carry:-6,    roll:0.4,   cr:-5.6  },
];

function ZCell({ v }) {
  if (v == null) return <td style={{ padding: '4px 8px', textAlign: 'right', font: 'var(--type-data)', fontSize: '11px', color: 'var(--text-muted)' }}>—</td>;
  const abs = Math.abs(v);
  const intensity = Math.min(abs / 4, 1);
  const bg = v > 0
    ? `rgba(52,211,153,${intensity * 0.35})`
    : `rgba(239,68,68,${intensity * 0.45})`;
  const color = v > 0 ? '#34d399' : '#f87171';
  return (
    <td style={{ padding: '4px 8px', textAlign: 'right', font: 'var(--type-data)', fontSize: '11px', background: bg, color: color, fontWeight: 600 }}>
      {v.toFixed(2)}
    </td>
  );
}

function BarTd({ v, max = 12 }) {
  const pct = Math.min(Math.abs(v) / max, 1) * 100;
  const pos = v >= 0;
  return (
    <td style={{ padding: '4px 8px', textAlign: 'right', font: 'var(--type-data)', fontSize: '11px', position: 'relative' }}>
      <div style={{ position: 'absolute', top: '3px', bottom: '3px', [pos?'right':'left']: '8px', width: `${pct * 0.5}%`, background: pos ? 'rgba(52,211,153,0.4)' : 'rgba(239,68,68,0.4)', borderRadius: '1px' }}></div>
      <span style={{ position: 'relative', color: pos ? '#34d399' : '#f87171' }}>{v.toFixed(2)}</span>
    </td>
  );
}

function MarketPricer() {
  const { useState } = React;
  const [instrType, setInstrType] = useState('TBond (Treasury)');
  const [subTerm, setSubTerm] = useState('1 – 3 Y');
  const [ts, setTs] = useState('00:34:05');
  const accent = 'var(--accent-cyan)';

  const Dropdown = ({ value, options, onChange, width = 'auto' }) => (
    <div style={{ position: 'relative', display: 'inline-block', width }}>
      <select value={value} onChange={e => onChange(e.target.value)} style={{
        appearance: 'none', WebkitAppearance: 'none',
        background: 'var(--surface-input)', border: '1px solid var(--border-default)',
        borderRadius: '5px', padding: '7px 28px 7px 10px', font: 'var(--type-data)', fontSize: '12px',
        color: 'var(--text-primary)', cursor: 'pointer', width: '100%',
      }}>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ position: 'absolute', right: '8px', top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}>
        <path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      </svg>
    </div>
  );

  const COLS = ['TICKER','COUPON','PTMYEAR','YIELD_CNBD','Z-SCORE','STATIONARY','HALFLIFE','VOLRATIO','CLOSE','BID','OFR','MID','DYLD (BP)','CARRY (3M,BP)','ROLL (3M,BP)','C+R (3M,BP)'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

      {/* Controls row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
        <div>
          <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '4px' }}>Instrument Type</div>
          <Dropdown value={instrType} options={INSTRUMENT_TYPES} onChange={setInstrType} width="160px" />
        </div>
        <div>
          <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '4px' }}>Sub-type / Term</div>
          <Dropdown value={subTerm} options={SUBTYPE_TERMS} onChange={setSubTerm} width="120px" />
        </div>
        <div style={{ marginTop: '16px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button onClick={() => { const n = new Date(); setTs(`${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')}:${String(n.getSeconds()).padStart(2,'0')}`); }} style={{
            padding: '7px 14px', font: 'var(--type-label)', fontSize: '11px',
            background: 'rgba(34,211,238,0.08)', border: `1px solid ${accent}`, borderRadius: '5px',
            color: accent, cursor: 'pointer', transition: 'all 0.15s',
          }}>↻ Refresh</button>
          <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', fontSize: '11px' }}>Updated {ts}</span>
        </div>
      </div>

      {/* Table label */}
      <div style={{ font: 'var(--type-label)', color: accent, fontSize: '11px', letterSpacing: '0.04em' }}>
        BOND PRICER — {instrType} · {subTerm}
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto', border: '1px solid var(--border-strong)', borderRadius: '6px' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', font: 'var(--type-data)', fontSize: '11px' }}>
          <thead>
            <tr style={{ background: 'var(--surface-panel)', borderBottom: '1px solid var(--border-strong)' }}>
              {COLS.map(c => (
                <th key={c} style={{ padding: '7px 8px', textAlign: c === 'TICKER' ? 'left' : 'right', font: 'var(--type-label)', fontSize: '9px', color: 'var(--text-muted)', letterSpacing: '0.05em', whiteSpace: 'nowrap', borderBottom: '1px solid var(--border-strong)' }}>
                  ⇅ {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {PRICER_ROWS.map((row, i) => (
              <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)', borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
                <td style={{ padding: '4px 8px', color: 'var(--text-primary)', whiteSpace: 'nowrap', fontWeight: 500 }}>{row.ticker}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-secondary)' }}>{row.cpn}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-secondary)' }}>{row.ptmy}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-primary)' }}>{row.yld}</td>
                <ZCell v={row.z} />
                <td style={{ padding: '4px 8px', textAlign: 'right', color: row.stat === 'YES' ? '#34d399' : 'var(--text-muted)', fontSize: '10px' }}>{row.stat}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-muted)' }}>{row.hl ?? '—'}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-secondary)' }}>{row.vr}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-primary)' }}>{row.cls}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-secondary)' }}>{row.bid}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-secondary)' }}>{row.ofr}</td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-primary)' }}>{row.mid}</td>
                <ZCell v={row.dyld} />
                <BarTd v={row.carry} />
                <BarTd v={row.roll} />
                <ZCell v={row.cr} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
window.MarketPricer = MarketPricer;
