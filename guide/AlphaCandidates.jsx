// Alpha Book > Candidates — relative-value scanner.
const _ns_ab = window.AtlasNexusDesignSystem_988df3;

function AlphaCandidates() {
  const { Panel, Checkbox, Button, Slider, Input, Select, SignalRow, Badge } = _ns_ab;
  const [cats, setCats] = React.useState({
    'Bond-Curve': true, 'Bond-Swap': true, 'Swap Spreads': true, 'Tenor Spreads': true,
    'Bond-Futures': false, 'Calendar Spreads': false, 'Futures-Swap': false,
  });
  const [z, setZ] = React.useState(2.0);
  const [cons, setCons] = React.useState(75);
  const [dir, setDir] = React.useState('All');
  const toggle = (k) => setCats((c) => ({ ...c, [k]: !c[k] }));

  const mr = [
    ['BUY', 'Repo7d-6m9m', 1.1], ['BUY', 'Repo7d-6m1y', 1.0], ['BUY', 'Repo7d-1y2y', 0.3],
    ['BUY', 'Repo7d-2y5y', 0.0], ['BUY', 'Shi3M-1y4y', 0.7], ['BUY', 'Shi3M-1y3y', 0.5],
    ['BUY', 'Repo7d-9m2y', 0.5], ['BUY', 'Shi3M-6m3y', 0.8], ['SELL', 'Shi3M-9m4y', -1.0],
  ];
  const mom = [['BUY', 'CDBCGB-30y', -0.9], ['BUY', 'CDBCGB-10y', -1.5]];
  const unc = [
    ['BUY', 'CDB-10s30s', 1.6], ['BUY', '210017-OTR', 2.6], ['BUY', 'CGB-5s10s', 1.0],
    ['BUY', 'CDB-5s10s', 0.6], ['BUY', 'CDBCGB-5y', -1.0], ['BUY', 'CGB-10s30s', 1.0],
  ];

  const Cluster = ({ color, title, count, note, rows }) => (
    <div style={{ marginTop: '20px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
        <span style={{ width: '6px', height: '16px', background: color, borderRadius: '1px' }} />
        <span style={{ font: 'var(--type-h3)', color: 'var(--text-primary)' }}>{title}</span>
        <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)' }}>{count} signals</span>
      </div>
      {note && <div style={{ font: 'var(--type-meta)', fontStyle: 'italic', color: 'var(--text-faint)', margin: '6px 0 8px' }}>{note}</div>}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px 32px' }}>
        {rows.map(([d, n, s], i) => <SignalRow key={i} direction={d} name={n} sigma={s} />)}
      </div>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div>
        <h1 style={{ margin: '0 0 8px', font: 'var(--type-h1)', color: 'var(--text-primary)' }}>Alpha Candidates Scanner</h1>
        <div style={{ font: 'var(--type-body)', color: 'var(--text-secondary)' }}>
          Scan for relative value opportunities across spread types. Filter by z-score deviation and check correlations before sizing.
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
        <Panel padding="14px 16px" style={{ background: 'var(--surface-raised)' }}>
          <div style={{ font: 'var(--type-label)', color: 'var(--text-primary)', marginBottom: '10px', fontSize: '12px' }}>Spread Categories</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px 24px' }}>
            {Object.keys(cats).map((k) => <Checkbox key={k} label={k} checked={cats[k]} onChange={() => toggle(k)} />)}
          </div>
        </Panel>

        <Panel padding="14px 16px" style={{ background: 'var(--surface-raised)' }}>
          <div style={{ font: 'var(--type-label)', color: 'var(--text-primary)', marginBottom: '10px', fontSize: '12px' }}>Direction Filter</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0 20px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {['All', 'BUY', 'SELL'].map((d) => (
                <label key={d} style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer',
                  font: 'var(--type-sm)', fontSize: '11px', color: 'var(--text-secondary)' }}>
                  <input type="radio" checked={dir === d} onChange={() => setDir(d)}
                    style={{ accentColor: 'var(--accent-purple)' }} />{d}
                </label>
              ))}
            </div>
            <div>
              <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', marginBottom: '6px', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Z-Score (σ)</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                <Input value={z.toFixed(1)} readOnly width="50px" />
              </div>
              <Slider min={1} max={3.5} step={0.1} value={z} onChange={setZ} />
              <div style={{ display: 'flex', justifyContent: 'space-between', font: 'var(--type-meta)', color: 'var(--text-muted)', marginTop: '5px', fontSize: '8px' }}>
                {['1.0', '1.5', '2.0', '2.5', '3.0', '3.5'].map((t) => <span key={t}>{t}</span>)}
              </div>
            </div>
          </div>
        </Panel>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
        <Button accent="cyan" icon="🔍">Scan Candidates</Button>
        <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)' }}>Found 27 candidates at 10:54:03</span>
      </div>

      <Panel title="Candidates" accent="amber">
        <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginBottom: '6px' }}>
          Regime: uncertain: 16, mean_reverting: 9, trending: 2
        </div>
        <Cluster color="var(--positive)" title="Mean-Reversion" count={9} rows={mr} />
        <Cluster color="var(--accent-amber)" title="Momentum / Carry" count={2} rows={mom} />
        <Cluster color="var(--text-muted)" title="Uncertain" count={16}
          note="Regime unresolved — check spread chart before trading." rows={unc} />
      </Panel>
    </div>
  );
}
window.AlphaCandidates = AlphaCandidates;
