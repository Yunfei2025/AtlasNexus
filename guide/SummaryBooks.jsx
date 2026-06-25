// Summary > Books — portfolio combination + allocation snapshot.
const _ns_sb = window.AtlasNexusDesignSystem_988df3;

const ALPHA_POSITIONS = [
  { name:'Repo7d-1y2y',  type:'Swap Spread',  dir:'BUY',  weight:1.8, pnl:+4.2,  pnl3m:+12.1, zscore: 1.21, entry:1.245, current:1.312, target:1.380, stop:1.210 },
  { name:'Repo7d-6m1y',  type:'Swap Spread',  dir:'BUY',  weight:1.8, pnl:+2.1,  pnl3m:+6.3,  zscore: 0.88, entry:1.180, current:1.221, target:1.260, stop:1.150 },
  { name:'CGB-10s30s',   type:'Bond Curve',   dir:'BUY',  weight:1.8, pnl:-1.4,  pnl3m:-4.2,  zscore:-0.61, entry:24.8,  current:23.4,  target:28.0,  stop:22.0  },
  { name:'CDBCGB-5y',    type:'Bond Swap',    dir:'BUY',  weight:1.8, pnl:+6.8,  pnl3m:+19.4, zscore: 2.03, entry:38.2,  current:45.0,  target:50.0,  stop:34.0  },
  { name:'250022.IB',    type:'Single Bond',  dir:'BUY',  weight:1.8, pnl:+1.2,  pnl3m:+3.8,  zscore: 0.54, entry:1.815, current:1.831, target:1.860, stop:1.790 },
  { name:'Repo7d-9m2y',  type:'Swap Spread',  dir:'SELL', weight:1.8, pnl:-0.8,  pnl3m:-2.4,  zscore:-0.34, entry:1.420, current:1.428, target:1.380, stop:1.460 },
  { name:'IRS-5s1s',     type:'IRS Curve',    dir:'BUY',  weight:1.5, pnl:+3.4,  pnl3m:+9.8,  zscore: 1.55, entry:18.4,  current:21.8,  target:25.0,  stop:16.0  },
  { name:'BdSwap-2Y',    type:'Bond Swap',    dir:'SELL', weight:1.5, pnl:-2.2,  pnl3m:-6.6,  zscore:-0.92, entry:28.1,  current:25.9,  target:22.0,  stop:31.0  },
];

function SummaryBooks() {
  const { Panel, KPICard, DataTable, HeatCell, SignedValue, Badge, Button } = _ns_sb;
  const [activeBook, setActiveBook] = React.useState('Alpha');

  const Op = ({ ch }) => (
    <div style={{ display: 'flex', alignItems: 'center', font: 'var(--type-display)', color: 'var(--text-faint)', padding: '0 6px' }}>{ch}</div>
  );

  const betaRows = [
    { asset: 'FX', universe: 'China Gov Bond', inst: 'GBPCNY', dur: '', cap: '1,051.82', wt: '10.52%' },
    { asset: 'FX', universe: 'DE Gov Bond', inst: 'EURCNY', dur: '', cap: '1,051.82', wt: '10.52%' },
    { asset: 'Rates', universe: 'China Gov Bond', inst: '250012.IB', dur: '0.95', cap: '1,817.11', wt: '18.17%' },
    { asset: 'Rates', universe: 'China Gov Bond', inst: '260010.IB', dur: '8.50', cap: '631.71', wt: '6.32%' },
    { asset: 'Commodities', universe: 'Base Metals', inst: 'Zinc', dur: '', cap: '4,000.00', wt: '20.00%' },
    { asset: 'Commodities', universe: 'Base Metals', inst: 'Aluminium', dur: '', cap: '1,899.58', wt: '19.00%' },
    { asset: 'Commodities', universe: 'Precious Metals', inst: 'Gold', dur: '', cap: '1,899.58', wt: '19.00%' },
    { asset: 'FX', universe: 'FX Universe', inst: 'USDCNY', dur: '', cap: '981.36', wt: '9.81%' },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <h1 style={{ margin: 0, font: 'var(--type-h1)', color: 'var(--text-primary)',
        borderBottom: '1px solid var(--accent-cyan)', paddingBottom: '12px' }}>Portfolio Combination</h1>

      <div style={{ display: 'flex', alignItems: 'stretch', gap: '0' }}>
        <KPICard style={{ flex: 1 }} label="Target Return" value="10.0%" accent="cyan" sub="Total Portfolio Target" />
        <Op ch="=" />
        <KPICard style={{ flex: 1 }} label="Risk Free Rate" value="1.5%" accent="green" sub="Cash / Treasury" />
        <Op ch="+" />
        <KPICard style={{ flex: 1 }} label="Beta Allocation" value="6.0%" accent="amber" sub="Strategic Asset Allocation" footnote="15.0% Vol × 0.4 Sharpe" />
        <Op ch="+" />
        <KPICard style={{ flex: 1 }} label="Alpha Overlay" value="2.5%" accent="red" sub="Tactical Adjustments" footnote="5.0% Vol × 0.5 IR" />
      </div>

      <Panel eyebrow="Portfolio Allocation Snapshot" accent="cyan"
        actions={
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)' }}>Beta edits saved at 10:53:22</span>
            <Button variant="outline" accent="cyan" size="sm">Refresh</Button>
            {/* Book switch */}
            <div style={{ display: 'flex', gap: '2px', background: 'var(--surface-input)', padding: '3px', borderRadius: '5px', border: '1px solid var(--border-default)' }}>
              {['Beta', 'Alpha'].map(b => (
                <button key={b} onClick={() => setActiveBook(b)} style={{
                  padding: '4px 14px', font: 'var(--type-label)', fontSize: '10px', border: 'none', borderRadius: '3px', cursor: 'pointer',
                  background: activeBook === b ? (b === 'Alpha' ? 'var(--accent-amber)' : 'var(--accent-blue)') : 'transparent',
                  color: activeBook === b ? '#fff' : 'var(--text-muted)', transition: 'all 0.15s',
                }}>{b} Book</button>
              ))}
            </div>
          </div>
        }>
        {activeBook === 'Beta' ? (
          <div>
            <div style={{ font: 'var(--type-h3)', color: 'var(--accent-blue)', borderBottom: '1px solid var(--accent-blue)', paddingBottom: '6px', marginBottom: '12px' }}>Beta Book — Asset Allocation</div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', font: 'var(--type-data)', fontSize: '11px' }}>
                <thead>
                  <tr style={{ background: 'var(--surface-panel)', borderBottom: '1px solid var(--border-strong)' }}>
                    {['Asset Type','Universe','Instrument','Duration','Capital (MM)','Weight (%)','Allocation'].map(h => (
                      <th key={h} style={{ padding: '7px 10px', textAlign: ['Asset Type','Universe','Instrument'].includes(h) ? 'left' : 'right',
                        font: 'var(--type-label)', fontSize: '9px', color: 'var(--text-muted)', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {betaRows.map((r, i) => {
                    const assetColor = r.asset === 'FX' ? 'var(--accent-cyan)' : r.asset === 'Rates' ? 'var(--accent-blue)' : 'var(--accent-amber)';
                    const assetBg   = r.asset === 'FX' ? 'rgba(34,211,238,0.12)' : r.asset === 'Rates' ? 'rgba(59,130,246,0.12)' : 'rgba(224,162,60,0.12)';
                    const wtNum = parseFloat(r.wt);
                    const capNum = parseFloat(r.cap.replace(/,/g,''));
                    const maxCap = 4000;
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)' }}>
                        <td style={{ padding: '5px 10px' }}>
                          <span style={{ padding: '2px 6px', borderRadius: '3px', fontSize: '9px', fontWeight: 600, background: assetBg, color: assetColor }}>{r.asset}</span>
                        </td>
                        <td style={{ padding: '5px 10px', color: 'var(--text-muted)', fontSize: '10px' }}>{r.universe}</td>
                        <td style={{ padding: '5px 10px', color: 'var(--text-primary)', fontWeight: 500 }}>{r.inst}</td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--text-secondary)' }}>{r.dur || '—'}</td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--text-primary)', fontWeight: 600 }}>{r.cap}</td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: assetColor, fontWeight: 600 }}>{r.wt}</td>
                        <td style={{ padding: '5px 10px', minWidth: '100px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <div style={{ flex: 1, height: '5px', background: 'var(--surface-input)', borderRadius: '3px' }}>
                              <div style={{ height: '100%', width: `${(capNum/maxCap)*100}%`, background: assetColor, borderRadius: '3px', opacity: 0.7 }}></div>
                            </div>
                            <span style={{ font: 'var(--type-meta)', fontSize: '9px', color: 'var(--text-muted)', minWidth: '32px' }}>{wtNum.toFixed(1)}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ) : (
          <div>
            <div style={{ font: 'var(--type-h3)', color: 'var(--accent-amber)', borderBottom: '1px solid var(--accent-amber)', paddingBottom: '6px', marginBottom: '12px' }}>Alpha Book — Live Positions</div>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', font: 'var(--type-data)', fontSize: '11px' }}>
                <thead>
                  <tr style={{ background: 'var(--surface-panel)', borderBottom: '1px solid var(--border-strong)' }}>
                    {['Name','Type','Dir','Weight','PnL (bp)','3M PnL','Z-Score','Entry','Current','Progress','Target','Stop'].map(h => (
                      <th key={h} style={{ padding: '7px 10px', textAlign: ['Name','Type','Dir'].includes(h) ? 'left' : 'right',
                        font: 'var(--type-label)', fontSize: '9px', color: 'var(--text-muted)', letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {ALPHA_POSITIONS.map((r, i) => {
                    const mn = Math.min(r.entry, r.stop), mx = Math.max(r.target, r.entry);
                    const rng = mx - mn || 1;
                    const entPct = ((r.entry - mn) / rng) * 100;
                    const curPct = ((r.current - mn) / rng) * 100;
                    const tgtPct = ((r.target - mn) / rng) * 100;
                    const gained = r.dir === 'BUY' ? curPct > entPct : curPct < entPct;
                    return (
                      <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.015)' }}>
                        <td style={{ padding: '5px 10px', color: 'var(--text-primary)', fontWeight: 500, whiteSpace: 'nowrap' }}>{r.name}</td>
                        <td style={{ padding: '5px 10px', color: 'var(--text-muted)', fontSize: '10px' }}>{r.type}</td>
                        <td style={{ padding: '5px 10px' }}>
                          <span style={{ padding: '2px 6px', borderRadius: '3px', fontSize: '9px', fontWeight: 600,
                            background: r.dir === 'BUY' ? 'rgba(52,211,153,0.15)' : 'rgba(239,68,68,0.15)',
                            color: r.dir === 'BUY' ? '#34d399' : '#f87171' }}>{r.dir}</span>
                        </td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--text-secondary)' }}>{r.weight.toFixed(1)}%</td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: r.pnl >= 0 ? '#34d399' : '#f87171', fontWeight: 600 }}>{r.pnl >= 0 ? '+' : ''}{r.pnl.toFixed(1)}</td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: r.pnl3m >= 0 ? '#34d399' : '#f87171', fontWeight: 600 }}>{r.pnl3m >= 0 ? '+' : ''}{r.pnl3m.toFixed(1)}</td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 600,
                          background: r.zscore > 0 ? `rgba(52,211,153,${Math.min(Math.abs(r.zscore)/2,1)*0.28})` : `rgba(239,68,68,${Math.min(Math.abs(r.zscore)/2,1)*0.38})`,
                          color: r.zscore > 0 ? '#34d399' : '#f87171' }}>{r.zscore.toFixed(2)}</td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--text-secondary)' }}>{r.entry}</td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: 'var(--text-primary)', fontWeight: 600 }}>{r.current}</td>
                        <td style={{ padding: '5px 10px', minWidth: '90px' }}>
                          <div style={{ position: 'relative', height: '6px', background: 'var(--surface-input)', borderRadius: '3px' }}>
                            <div style={{ position: 'absolute', top: 0, bottom: 0,
                              left: `${Math.min(entPct, curPct)}%`, width: `${Math.abs(curPct - entPct)}%`,
                              background: gained ? 'rgba(52,211,153,0.5)' : 'rgba(239,68,68,0.5)', borderRadius: '3px' }}></div>
                            <div style={{ position: 'absolute', top: '-2px', bottom: '-2px', left: `${curPct}%`, width: '3px',
                              background: 'var(--accent-amber)', borderRadius: '1px', transform: 'translateX(-50%)' }}></div>
                            <div style={{ position: 'absolute', top: '-1px', bottom: '-1px', left: `${tgtPct}%`, width: '2px',
                              background: 'rgba(52,211,153,0.8)', borderRadius: '1px', transform: 'translateX(-50%)' }}></div>
                          </div>
                        </td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: '#34d399' }}>{r.target}</td>
                        <td style={{ padding: '5px 10px', textAlign: 'right', color: '#f87171' }}>{r.stop}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </Panel>
    </div>
  );
}
window.SummaryBooks = SummaryBooks;
