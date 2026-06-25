// AtlasNexus Daily — app header + book/sub-tab navigation shell.
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

function AppShell({ book, setBook, sub, setSub, children }) {
  const accent = BOOK_ACCENT[book] || 'cyan';
  const subtabs = SUBTABS[book] || [];
  return (
    <div style={{ maxWidth: 'var(--app-max-w)', margin: '0 auto', padding: '26px var(--app-pad-x) 60px' }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '22px' }}>
        <div>
          <div style={{ font: 'var(--type-display)', letterSpacing: 'var(--ls-display)', color: 'var(--text-primary)' }}>
            AtlasNexus <span style={{ color: 'var(--text-faint)' }}>·</span> Daily
          </div>
          <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginTop: '8px' }}>
            Latest EOD: run_id=20260617-eod-210752 | mode=eod | asof=2026-06-17 | generated_at=2026-06-17T13:08:58.345494 | status=completed
          </div>
          <div style={{ font: 'var(--type-meta)', color: 'var(--text-faint)', marginTop: '3px' }}>Updated 10:53:34</div>
        </div>
        <StatusPill label="Wind" value="—" status="live" />
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
