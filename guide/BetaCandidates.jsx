// Beta Book > Candidates — factor selection pool + train/predict.
const _ns_bb = window.AtlasNexusDesignSystem_988df3;

function BetaCandidates() {
  const { Panel, Checkbox, Button, Input } = _ns_bb;
  const [factors, setFactors] = React.useState({
    'CN-IRDL': true, 'CN-IRSL': true, 'CN-IRCV': true,
    'FXDL.USDCNY': true, 'CMDL.AU': true,
  });
  const toggle = (k) => setFactors((f) => ({ ...f, [k]: !f[k] }));

  const domiciles = ['CN', 'US', 'EU', 'JP', 'UK'];
  const flags = { CN: '🇨🇳', US: '🇺🇸', EU: '🇪🇺', JP: '🇯🇵', UK: '🇬🇧' };
  const irKinds = ['IRDL', 'IRSL', 'IRCV'];

  const GroupLabel = ({ icon, children }) => (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', margin: '24px 0 6px',
      font: 'var(--type-h3)', color: 'var(--accent-cyan)' }}>
      <span>{icon}</span>{children}
    </div>
  );
  const Note = ({ children }) => (
    <div style={{ font: 'var(--type-meta)', fontStyle: 'italic', color: 'var(--text-faint)', marginBottom: '12px' }}>{children}</div>
  );

  const fx = ['FXDL.USDCNY', 'FXDL.EURCNY', 'FXDL.JPYCNY', 'FXDL.GBPCNY'];
  const eq = ['EQDL.IF (CSI 300)', 'EQDL.IC (CSI 500)', 'EQDL.IH (SSE 50)', 'EQDL.IM (CSI 1000)'];
  const cm = ['CMDL.AU (Gold)', 'CMDL.AG (Silver)', 'CMDL.AL (Aluminium)', 'CMDL.CU (Copper)',
    'CMDL.ZN (Zinc)', 'CMDL.SC (Crude Oil)', 'CMDL.RB (Rebar)', 'CMDL.LC (Live Hog)',
    'CMDL.SA (Soda Ash)', 'CMDL.JM (Coking Coal)', 'CMDL.EC (Euro Gas)'];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <Panel title="🎯 Factor Selection Pool" accent="blue">
        <div style={{ font: 'var(--type-body)', color: 'var(--text-secondary)', marginBottom: '4px' }}>
          Select factors to include in correlation analysis:
        </div>

        <GroupLabel icon="📊">Interest Rates (IR)</GroupLabel>
        <Note>Each domicile covers: IRDL (Level · Bullish/Bearish), IRSL (Slope · Flattener/Steepener), IRCV (Curvature · Concave/Convex)</Note>
        <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap' }}>
          {domiciles.map((d) => (
            <div key={d} style={{ flex: '1', minWidth: '150px', background: 'var(--surface-raised)',
              border: '1px solid var(--border-default)', borderRadius: 'var(--radius-sm)', padding: '12px 14px' }}>
              <div style={{ textAlign: 'center', font: 'var(--type-h3)', color: 'var(--accent-cyan)', marginBottom: '10px' }}>
                {flags[d]} {d}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {irKinds.map((k) => {
                  const key = `${d}-${k}`;
                  return <Checkbox key={key} label={k} checked={!!factors[key]} onChange={() => toggle(key)} />;
                })}
              </div>
            </div>
          ))}
        </div>

        <GroupLabel icon="💱">Foreign Exchange (FX)</GroupLabel>
        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
          {fx.map((k) => <Checkbox key={k} label={k} checked={!!factors[k]} onChange={() => toggle(k)} />)}
        </div>

        <GroupLabel icon="📈">Equities (EQ)</GroupLabel>
        <Note>CSI equity index futures — price return factors</Note>
        <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>
          {eq.map((k) => <Checkbox key={k} label={k} checked={!!factors[k]} onChange={() => toggle(k)} />)}
        </div>

        <GroupLabel icon="🌐">Commodities (CM)</GroupLabel>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px 24px' }}>
          {cm.map((k) => {
            const key = k.split(' ')[0];
            return <Checkbox key={key} label={k} checked={!!factors[key]} onChange={() => toggle(key)} />;
          })}
        </div>
      </Panel>

      <Panel title="🤖 Train Model & Predict" accent="blue">
        <div style={{ font: 'var(--type-body)', color: 'var(--text-secondary)', fontStyle: 'italic', marginBottom: '16px' }}>
          Train the factor model on data up to the first day of the current month (no recent daily data — reduces overfitting). Outputs the latest signal state and top driving indicators.
        </div>
        <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-end' }}>
          <Input label="Train (months)" defaultValue="12" width="70px" />
          <Input label="IC thr" defaultValue="0.05" width="70px" />
          <Input label="Top N" defaultValue="8" width="60px" />
          <Button accent="purple">Train Model</Button>
          <Button accent="cyan">Predict</Button>
        </div>
      </Panel>
    </div>
  );
}
window.BetaCandidates = BetaCandidates;
