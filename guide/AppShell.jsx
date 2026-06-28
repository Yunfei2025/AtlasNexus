// AtlasNexus Daily — app header + book/sub-tab navigation shell.
const { useState, useEffect } = React;
const { Tabs, StatusPill } = window.AtlasNexusDesignSystem_988df3;

const BOOK_ACCENT = {
  'Market': 'cyan', 'Beta Book': 'blue', 'Alpha Book': 'amber',
  'Summary': 'cyan', 'Run Center': 'teal',
};
const SUBTABS = {
  'Market': ['Data', 'Trend', 'Pricer', 'Surface', 'Curves'],
  'Beta Book': ['Candidates', 'Portfolio', 'Backtest', 'Factor', 'Bond', 'Futures'],
  'Alpha Book': ['Candidates', 'Portfolio', 'Backtest', 'Spread', 'Pairs', 'Volatility'],
  'Summary': ['Books', 'Risk', 'Tickets'],
  'Run Center': [],
};

function MetaChip({ label, value, valueColor }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: '2px',
      background: 'var(--surface-panel)', border: `1px solid var(--border-default)`,
      borderRadius: '4px', padding: '5px 11px', userSelect: 'none',
    }}>
      <span style={{ font: 'var(--type-th)', color: 'var(--text-faint)' }}>{label}</span>
      <span style={{ font: 'var(--type-meta)', color: valueColor || 'var(--text-secondary)' }}>{value}</span>
    </div>
  );
}

function LiveClock() {
  const [time, setTime] = useState(() =>
    new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  );
  useEffect(() => {
    const id = setInterval(() => setTime(
      new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    ), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <div style={{
      font: 'var(--type-meta)', color: 'var(--text-secondary)',
      letterSpacing: '0.04em', minWidth: '68px', textAlign: 'center',
    }}>{time}</div>
  );
}

function AppShell({ book, setBook, sub, setSub, children }) {
  const accent = BOOK_ACCENT[book] || 'cyan';
  const subtabs = SUBTABS[book] || [];
  return (
    <div style={{ maxWidth: 'var(--app-max-w)', margin: '0 auto', padding: '26px var(--app-pad-x) 60px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '22px', gap: '16px' }}>
        <div>
          <div style={{ font: 'var(--type-display)', letterSpacing: 'var(--ls-display)', color: 'var(--text-primary)' }}>
            AtlasNexus <span style={{ color: 'var(--text-faint)' }}>·</span> Daily
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <MetaChip label="AS OF" value="2026-06-28" />
          <MetaChip label="STATUS" value="✓  COMPLETED" valueColor="var(--accent-green)" />
          <div style={{ width: '1px', height: '34px', background: 'var(--border-default)', flexShrink: 0 }} />
          <LiveClock />
          <div style={{ width: '1px', height: '34px', background: 'var(--border-default)', flexShrink: 0 }} />
          <StatusPill label="Wind" value="—" status="live" />
        </div>
      </div>

      {/* Main book tabs */}
      <Tabs variant="main" accent={accent} value={book}
        onChange={(b) => { setBook(b); setSub((SUBTABS[b] || ['Data'])[0]); }}
        items={['Market', 'Beta Book', 'Alpha Book', 'Summary', 'Run Center']} />

      {/* Sub tabs */}
      {subtabs.length > 0 && (
        <Tabs variant="sub" accent={accent} value={sub} onChange={setSub} items={subtabs}
          style={{ marginBottom: '24px' }} />
      )}
      {subtabs.length === 0 && <div style={{ height: '24px' }} />}

      {children}
    </div>
  );
}
window.AppShell = AppShell;
window.BOOK_ACCENT = BOOK_ACCENT;
