// Beta Book → Backtest — individual spread vs portfolio backtesting
const _ns_bb = window.AtlasNexusDesignSystem_988df3;

const SPREAD_TYPES = ['Bond-Curve (Treasury)', 'Bond-Swap', 'Swap Spreads', 'Tenor Spreads', 'Bond-Futures', 'Calendar Spreads'];
const INSTRUMENTS = ['10Y UST', '5Y UST', '30Y UST', '10Y-30Y Butterfly', '2Y-10Y Curve'];
const FACTOR_POOL = ['DUR', 'CONV', 'CS01', 'DV01', 'TVIX', 'SKEW'];
const BACKTEST_PERIODS = ['1 Year', '2 Years', '3 Years', '5 Years'];

function BacktestBeta() {
  const { useState } = React;
  const [mode, setMode] = useState('individual'); // 'individual' or 'portfolio'
  
  // Individual Spread mode
  const [spreadType, setSpreadType] = useState('Bond-Curve (Treasury)');
  const [instrument, setInstrument] = useState('10Y UST');
  const [minHolding, setMinHolding] = useState('7');
  const [entryZ, setEntryZ] = useState('2');
  const [exitZ, setExitZ] = useState('0.5');
  const [stopLoss, setStopLoss] = useState('4');
  const [backtestPeriod, setBacktestPeriod] = useState('2 Years');
  
  // Portfolio mode
  const [capital, setCapital] = useState('10');
  const [capitalUnit, setCapitalUnit] = useState('MM');
  const [corrLookback, setCorrLookback] = useState('252');
  const [topPairs, setTopPairs] = useState('3');
  const [allocationMode, setAllocationMode] = useState('equal');
  const [dateMode, setDateMode] = useState('preset');
  
  const MOCK_RESULTS = {
    annualReturn: 3.26,
    maxDrawdown: -8.42,
    sharpeRatio: 0.94,
    calmarRatio: 0.39,
    winRate: 58.3,
    profitFactor: 1.62,
    avgTrade: 1240,
  };

  // Dropdown component
  const Dropdown = ({ value, options, onChange }) => (
    <div style={{
      background: 'var(--surface-input)',
      border: '1px solid var(--border-default)',
      borderRadius: '6px',
      padding: '10px 12px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      cursor: 'pointer',
      font: 'var(--type-data)',
      color: 'var(--text-primary)',
    }}>
      <span>{value}</span>
      <svg width="13" height="13" fill="none" viewBox="0 0 16 16">
        <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      {/* Header */}
      <div>
        <h1 style={{ margin: '0 0 8px', font: 'var(--type-h1)', color: 'var(--text-primary)' }}>Beta Backtest</h1>
        <div style={{ font: 'var(--type-body)', color: 'var(--text-secondary)' }}>
          Backtest individual spread trades or the full portfolio using historical data. Evaluate strategy performance with z-score (mean-reversion or momentum) or directional-change trend rules.
        </div>
      </div>

      {/* Mode Toggle: Individual Spread vs Portfolio */}
      <div style={{ display: 'flex', gap: '4px', background: 'var(--surface-input)', padding: '4px', borderRadius: '6px', border: '1px solid var(--border-default)', width: 'fit-content' }}>
        {[
          { key: 'individual', label: 'Individual Factors' },
          { key: 'portfolio', label: 'Portfolio' },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setMode(key)}
            style={{
              padding: '8px 16px',
              font: 'var(--type-label)',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              background: mode === key ? 'var(--accent-green)' : 'transparent',
              color: mode === key ? 'var(--text-on-accent)' : 'var(--text-muted)',
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => {
              if (mode !== key) e.target.style.background = 'rgba(47, 157, 107, 0.16)';
            }}
            onMouseLeave={(e) => {
              if (mode !== key) e.target.style.background = 'transparent';
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* INDIVIDUAL FACTORS MODE */}
      {mode === 'individual' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '16px', alignItems: 'start' }}>
          {/* Factor Selection — LEFT */}
          <div style={{
            background: 'var(--surface-panel)',
            border: '1px solid var(--border-strong)',
            borderRadius: '6px',
            padding: '14px 16px',
          }}>
            <h2 style={{ margin: '0 0 10px', font: 'var(--type-h3)', color: 'var(--text-primary)' }}>Factor Selection</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Spread Type:</label>
                <Dropdown value={spreadType} options={SPREAD_TYPES} onChange={setSpreadType} />
              </div>
              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Instrument:</label>
                <Dropdown value={instrument} options={INSTRUMENTS} onChange={setInstrument} />
              </div>
              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Min Holding (days):</label>
                <input type="text" value={minHolding} onChange={(e) => setMinHolding(e.target.value)} style={{ width: '100px', background: 'var(--surface-input)', border: '1px solid var(--border-default)', borderRadius: '6px', padding: '8px 10px', font: 'var(--type-data)', color: 'var(--text-primary)', boxSizing: 'border-box' }} />
              </div>
            </div>
          </div>

          {/* Strategy Parameters — RIGHT */}
          <div style={{
            background: 'var(--surface-panel)',
            border: '1px solid var(--border-strong)',
            borderRadius: '6px',
            padding: '14px 16px',
          }}>
            <h2 style={{ margin: '0 0 10px', font: 'var(--type-h3)', color: 'var(--text-primary)' }}>Strategy Parameters</h2>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '12px' }}>
              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Entry Z-Score:</label>
                <input type="text" value={entryZ} onChange={(e) => setEntryZ(e.target.value)} style={{ width: '100%', background: 'var(--surface-input)', border: '1px solid var(--border-default)', borderRadius: '6px', padding: '8px 10px', font: 'var(--type-data)', color: 'var(--text-primary)', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Exit Z-Score:</label>
                <input type="text" value={exitZ} onChange={(e) => setExitZ(e.target.value)} style={{ width: '100%', background: 'var(--surface-input)', border: '1px solid var(--border-default)', borderRadius: '6px', padding: '8px 10px', font: 'var(--type-data)', color: 'var(--text-primary)', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Stop Loss (σ):</label>
                <input type="text" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} style={{ width: '100%', background: 'var(--surface-input)', border: '1px solid var(--border-default)', borderRadius: '6px', padding: '8px 10px', font: 'var(--type-data)', color: 'var(--text-primary)', boxSizing: 'border-box' }} />
              </div>
              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Backtest Period:</label>
                <Dropdown value={backtestPeriod} options={BACKTEST_PERIODS} onChange={setBacktestPeriod} />
              </div>
            </div>
            <button style={{ padding: '9px 18px', font: 'var(--type-label)', background: 'var(--accent-green)', color: 'var(--text-on-accent)', border: 'none', borderRadius: '6px', cursor: 'pointer', transition: 'filter 0.15s' }}
              onMouseEnter={(e) => e.target.style.filter = 'brightness(1.1)'}
              onMouseLeave={(e) => e.target.style.filter = 'brightness(1)'}
            >▶ Run Individual Factors Backtest</button>
          </div>
        </div>
      )}

      {/* PORTFOLIO MODE */}
      {mode === 'portfolio' && (
        <>
        <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '16px', alignItems: 'start', maxWidth: '1200px' }}>
          {/* Strategy Info — LEFT */}
          <div style={{
            background: 'var(--surface-panel)',
            border: '1px solid var(--border-strong)',
            borderRadius: '6px',
            padding: '14px 16px',
            minWidth: '280px',
            maxWidth: '320px',
          }}>
            <h2 style={{ margin: '0 0 10px', font: 'var(--type-h3)', color: 'var(--text-primary)' }}>Strategy</h2>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginBottom: '4px' }}>Factor Pool</div>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {FACTOR_POOL.map(f => (
                    <span key={f} style={{
                      font: 'var(--type-meta)',
                      color: 'var(--text-primary)',
                      background: 'rgba(47, 157, 107, 0.16)',
                      border: '1px solid var(--accent-green)',
                      borderRadius: '4px',
                      padding: '4px 8px',
                    }}>
                      {f}
                    </span>
                  ))}
                </div>
              </div>
              <div style={{ display: 'flex', gap: '16px' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginBottom: '4px' }}>Lookback</div>
                  <div style={{ font: 'var(--type-data)', color: 'var(--text-primary)' }}>
                    {backtestPeriod}
                  </div>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginBottom: '4px' }}>Capital</div>
                  <div style={{ font: 'var(--type-data)', color: 'var(--text-primary)' }}>
                    {capital} {capitalUnit}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Parameters — MIDDLE */}
          <div style={{
            background: 'var(--surface-panel)',
            border: '1px solid var(--border-strong)',
            borderRadius: '6px',
            padding: '14px 16px',
            minWidth: '500px',
            maxWidth: '700px',
          }}>
            <h2 style={{ margin: '0 0 10px', font: 'var(--type-h3)', color: 'var(--text-primary)' }}>Parameters</h2>

            {/* 4-column grid */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '10px', marginBottom: '12px' }}>
              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>
                  Backtest Lookback
                </label>
                <Dropdown value={backtestPeriod} options={BACKTEST_PERIODS} onChange={setBacktestPeriod} />
              </div>

              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>
                  Capital
                </label>
                <input
                  type="text"
                  value={capital}
                  onChange={(e) => setCapital(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'var(--surface-input)',
                    border: '1px solid var(--border-default)',
                    borderRadius: '6px',
                    padding: '8px 10px',
                    font: 'var(--type-data)',
                    color: 'var(--text-primary)',
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>
                  Unit
                </label>
                <Dropdown value={capitalUnit} options={['MM', 'K', 'Dollars']} onChange={setCapitalUnit} />
              </div>

              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>
                  Correlation Lookback
                </label>
                <input
                  type="text"
                  value={corrLookback}
                  onChange={(e) => setCorrLookback(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'var(--surface-input)',
                    border: '1px solid var(--border-default)',
                    borderRadius: '6px',
                    padding: '8px 10px',
                    font: 'var(--type-data)',
                    color: 'var(--text-primary)',
                    boxSizing: 'border-box',
                  }}
                />
              </div>

              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>
                  Top Low-Corr Pairs
                </label>
                <input
                  type="text"
                  value={topPairs}
                  onChange={(e) => setTopPairs(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'var(--surface-input)',
                    border: '1px solid var(--border-default)',
                    borderRadius: '6px',
                    padding: '8px 10px',
                    font: 'var(--type-data)',
                    color: 'var(--text-primary)',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>

            {/* Segmented Controls */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '12px' }}>
              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>
                  Date Mode
                </label>
                <div style={{ display: 'flex', gap: '4px', background: 'var(--surface-input)', padding: '4px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
                  {['preset', 'custom'].map(m => (
                    <button
                      key={m}
                      onClick={() => setDateMode(m)}
                      style={{
                        flex: 1,
                        padding: '6px 10px',
                        font: 'var(--type-label)',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        background: dateMode === m ? 'var(--accent-green)' : 'transparent',
                        color: dateMode === m ? 'var(--text-on-accent)' : 'var(--text-muted)',
                        transition: 'all 0.15s',
                      }}
                      onMouseEnter={(e) => {
                        if (dateMode !== m) e.target.style.background = 'rgba(47, 157, 107, 0.16)';
                      }}
                      onMouseLeave={(e) => {
                        if (dateMode !== m) e.target.style.background = 'transparent';
                      }}
                    >
                      {m === 'preset' ? 'Preset' : 'Custom'}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>
                  Allocation Mode
                </label>
                <div style={{ display: 'flex', gap: '4px', background: 'var(--surface-input)', padding: '4px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
                  {['equal', 'risk'].map(m => (
                    <button
                      key={m}
                      onClick={() => setAllocationMode(m)}
                      style={{
                        flex: 1,
                        padding: '6px 10px',
                        font: 'var(--type-label)',
                        border: 'none',
                        borderRadius: '4px',
                        cursor: 'pointer',
                        background: allocationMode === m ? 'var(--accent-green)' : 'transparent',
                        color: allocationMode === m ? 'var(--text-on-accent)' : 'var(--text-muted)',
                        transition: 'all 0.15s',
                      }}
                      onMouseEnter={(e) => {
                        if (allocationMode !== m) e.target.style.background = 'rgba(47, 157, 107, 0.16)';
                      }}
                      onMouseLeave={(e) => {
                        if (allocationMode !== m) e.target.style.background = 'transparent';
                      }}
                    >
                      {m === 'equal' ? 'Equal Weight' : 'Risk Parity'}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Action Buttons — RIGHT */}
          <div style={{
            background: 'var(--surface-panel)',
            border: '1px solid var(--border-strong)',
            borderRadius: '6px',
            padding: '14px 16px',
            minWidth: '140px',
            display: 'flex',
            flexDirection: 'column',
            gap: '10px',
          }}>
            <h2 style={{ margin: '0', font: 'var(--type-h3)', color: 'var(--text-primary)', fontSize: '12px' }}>Actions</h2>
            <button style={{
              padding: '10px 12px',
              font: 'var(--type-label)',
              background: 'var(--accent-green)',
              color: 'var(--text-on-accent)',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              transition: 'filter 0.15s',
              fontSize: '10px',
            }}
            onMouseEnter={(e) => e.target.style.filter = 'brightness(1.1)'}
            onMouseLeave={(e) => e.target.style.filter = 'brightness(1)'}
            >
              Run Analysis
            </button>
            <button style={{
              padding: '10px 12px',
              font: 'var(--type-label)',
              background: 'rgba(47, 157, 107, 0.16)',
              color: 'var(--accent-green)',
              border: '1px solid var(--accent-green)',
              borderRadius: '6px',
              cursor: 'pointer',
              transition: 'all 0.15s',
              fontSize: '10px',
            }}
            onMouseEnter={(e) => e.target.style.background = 'rgba(47, 157, 107, 0.25)'}
            onMouseLeave={(e) => e.target.style.background = 'rgba(47, 157, 107, 0.16)'}
            >
              Generate Report
            </button>
            <button style={{
              padding: '10px 12px',
              font: 'var(--type-label)',
              background: 'transparent',
              color: 'var(--text-muted)',
              border: '1px solid var(--border-default)',
              borderRadius: '6px',
              cursor: 'pointer',
              transition: 'all 0.15s',
              fontSize: '10px',
            }}
            onMouseEnter={(e) => {
              e.target.style.borderColor = 'var(--border-strong)';
              e.target.style.color = 'var(--text-primary)';
            }}
            onMouseLeave={(e) => {
              e.target.style.borderColor = 'var(--border-default)';
              e.target.style.color = 'var(--text-muted)';
            }}
            >
              Download
            </button>
          </div>
        </div>
        </>
      )}

      {/* KPI Metrics Grid (shown for both modes after running) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: '12px' }}>
        {[
          { label: 'Ann. Return', value: MOCK_RESULTS.annualReturn.toFixed(2) + '%', color: 'var(--positive)' },
          { label: 'Max Drawdown', value: MOCK_RESULTS.maxDrawdown.toFixed(2) + '%', color: 'var(--negative)' },
          { label: 'Sharpe Ratio', value: MOCK_RESULTS.sharpeRatio.toFixed(2), color: 'var(--text-primary)' },
          { label: 'Calmar Ratio', value: MOCK_RESULTS.calmarRatio.toFixed(2), color: 'var(--text-primary)' },
          { label: 'Win Rate', value: MOCK_RESULTS.winRate.toFixed(1) + '%', color: 'var(--positive)' },
          { label: 'Profit Factor', value: MOCK_RESULTS.profitFactor.toFixed(2), color: 'var(--positive)' },
          { label: 'Avg Trade', value: '$' + MOCK_RESULTS.avgTrade.toLocaleString(), color: 'var(--text-primary)' },
        ].map((kpi, i) => (
          <div key={i} style={{
            background: 'var(--surface-panel)',
            border: '1px solid var(--border-strong)',
            borderRadius: '8px',
            padding: '12px 8px',
            textAlign: 'center',
          }}>
            <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', marginBottom: '6px' }}>
              {kpi.label}
            </div>
            <div style={{ font: 'var(--type-data)', color: kpi.color, lineHeight: 1.2 }}>
              {kpi.value}
            </div>
          </div>
        ))}
      </div>

      {/* Chart Card */}
      <div style={{
        background: 'var(--surface-panel)',
        border: '1px solid var(--border-strong)',
        borderRadius: '8px',
        padding: '16px',
        minHeight: '320px',
        display: 'flex',
        flexDirection: 'column',
      }}>
        <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', marginBottom: '16px' }}>
          {mode === 'individual' ? 'P&L Over Time — Individual Factors' : 'Allocation Over Time — Portfolio'}
        </div>
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', font: 'var(--type-meta)' }}>
          <div style={{ textAlign: 'center' }}>
            <svg width="240" height="140" viewBox="0 0 240 140" fill="none" style={{ opacity: 0.4, marginBottom: '12px' }}>
              <path d="M20 120 Q60 100 100 80 T180 40" stroke="var(--accent-cyan)" strokeWidth="2" fill="none" />
              <circle cx="100" cy="80" r="3" fill="var(--accent-cyan)" />
              <circle cx="180" cy="40" r="3" fill="var(--accent-cyan)" />
            </svg>
            <div>Chart — connect to your data source</div>
          </div>
        </div>
      </div>
    </div>
  );
}

window.BacktestBeta = BacktestBeta;
