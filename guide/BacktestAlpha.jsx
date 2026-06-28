// Alpha Book → Backtest — individual spread vs portfolio backtesting
const _ns_ba = window.AtlasNexusDesignSystem_988df3;

const SPREAD_TYPES = ['Bond-Curve (Treasury)', 'Bond-Swap', 'Swap Spreads', 'Tenor Spreads', 'Bond-Futures', 'Calendar Spreads'];
const INSTRUMENTS = ['210013.IB', '10Y UST', '5Y UST', '30Y UST', '10Y-30Y Butterfly', '2Y-10Y Curve'];
const BACKTEST_PERIODS = ['1 Year', '2 Years', '3 Years', '5 Years'];

const PORTFOLIO_ASSETS = [
  { name: 'Repo7d-1y2y', weight: '1.8%', dir: 'BUY' },
  { name: 'Repo7d-6m1y', weight: '1.8%', dir: 'BUY' },
  { name: 'CGB-10s30s',  weight: '1.8%', dir: 'BUY' },
  { name: 'T',           weight: '1.8%', dir: 'BUY' },
  { name: 'Repo7d-6m2y', weight: '1.8%', dir: 'BUY' },
  { name: 'Repo7d-9m2y', weight: '1.8%', dir: 'BUY' },
  { name: 'CDBCGB-5y',   weight: '1.8%', dir: 'BUY' },
  { name: '250022.IB',   weight: '1.8%', dir: 'BUY' },
];

const MOCK_INDIVIDUAL = {
  totalTrades: 13,
  winRate: 38.5,
  totalPnl: -13.4,
  avgPnl: -1.03,
  avgHold: 8,
  sharpe: -0.73,
  maxDD: 16.6,
};

function BacktestAlpha() {
  const { useState } = React;
  const [mode, setMode] = useState('individual');

  // Individual Spread state
  const [spreadType, setSpreadType] = useState('Bond-Curve (Treasury)');
  const [instrument, setInstrument] = useState('210013.IB');
  const [tradeStyle, setTradeStyle] = useState('trend');
  const [minHolding, setMinHolding] = useState('7');
  const [theta, setTheta] = useState('0.02');
  const [momWindow, setMomWindow] = useState('20');
  const [volWindow, setVolWindow] = useState('60');
  const [trailMult, setTrailMult] = useState('1.5');
  const [momBuffer, setMomBuffer] = useState('0');
  const [allowShort, setAllowShort] = useState(true);
  const [showResults, setShowResults] = useState(true);

  // Portfolio state
  const [backtestPeriod, setBacktestPeriod] = useState('2 Years');
  const [initialCapital, setInitialCapital] = useState('100');
  const [txCost, setTxCost] = useState('0.5');
  const [dateMode, setDateMode] = useState('preset');

  const accentAmber = 'var(--accent-amber)';
  const accentAmberSoft = 'var(--accent-amber-soft)';

  const Dropdown = ({ value, options, onChange }) => (
    <div style={{
      background: 'var(--surface-input)',
      border: '1px solid var(--border-default)',
      borderRadius: '6px',
      padding: '8px 10px',
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'center',
      cursor: 'pointer',
      font: 'var(--type-data)',
      color: 'var(--text-primary)',
    }}>
      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
      <svg width="12" height="12" fill="none" viewBox="0 0 16 16" style={{ flexShrink: 0, marginLeft: '6px' }}>
        <path d="M4 6l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </div>
  );

  const Stepper = ({ value, onChange }) => {
    const step = (delta) => {
      const n = parseFloat(value) || 0;
      const precision = value.includes('.') ? value.split('.')[1].length : 0;
      const inc = precision > 0 ? Math.pow(10, -precision) : 1;
      onChange(String(Math.round((n + delta * inc) * 1e9) / 1e9));
    };
    return (
      <div style={{ display: 'flex', alignItems: 'center', border: '1px solid var(--border-default)', borderRadius: '6px', overflow: 'hidden', background: 'var(--surface-input)' }}>
        <button onClick={() => step(-1)} style={{ width: '28px', height: '32px', border: 'none', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRight: '1px solid var(--border-default)' }}>{'-'}</button>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          style={{ flex: 1, width: '60px', border: 'none', background: 'transparent', font: 'var(--type-data)', color: 'var(--text-primary)', textAlign: 'center', padding: '6px 4px', outline: 'none' }}
        />
        <button onClick={() => step(1)} style={{ width: '28px', height: '32px', border: 'none', background: 'transparent', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderLeft: '1px solid var(--border-default)' }}>{'+'}</button>
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {/* Header */}
      <div>
        <h1 style={{ margin: '0 0 6px', font: 'var(--type-h1)', color: 'var(--text-primary)' }}>Alpha Backtest</h1>
        <div style={{ font: 'var(--type-body)', color: 'var(--text-secondary)', maxWidth: '800px' }}>
          Backtest individual spread trades or the full portfolio using historical data. Evaluate strategy performance with z-score (mean-reversion or momentum) or directional-change trend rules.
        </div>
      </div>

      {/* Mode Toggle */}
      <div style={{ display: 'flex', gap: '0', background: 'var(--surface-input)', borderRadius: '6px', border: '1px solid var(--border-default)', width: 'fit-content', padding: '3px' }}>
        {[{ key: 'individual', label: 'Individual Spread' }, { key: 'portfolio', label: 'Portfolio' }].map(({ key, label }) => (
          <button key={key} onClick={() => setMode(key)} style={{
            padding: '7px 16px',
            font: 'var(--type-label)',
            border: 'none',
            borderRadius: '4px',
            cursor: 'pointer',
            background: mode === key ? accentAmber : 'transparent',
            color: mode === key ? 'var(--text-on-accent)' : 'var(--text-muted)',
            transition: 'all 0.15s',
          }}
          onMouseEnter={(e) => { if (mode !== key) e.target.style.background = accentAmberSoft; }}
          onMouseLeave={(e) => { if (mode !== key) e.target.style.background = 'transparent'; }}
          >{label}</button>
        ))}
      </div>

      {/* ── INDIVIDUAL SPREAD MODE ── */}
      {mode === 'individual' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr auto', gap: '14px', alignItems: 'start' }}>

            {/* Spread Selection — LEFT */}
            <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '14px 16px' }}>
              <h2 style={{ margin: '0 0 12px', font: 'var(--type-h3)', color: 'var(--text-primary)' }}>Spread Selection</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div>
                  <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '5px' }}>Spread Type</label>
                  <Dropdown value={spreadType} options={SPREAD_TYPES} onChange={setSpreadType} />
                </div>
                <div>
                  <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '5px' }}>Instrument</label>
                  <Dropdown value={instrument} options={INSTRUMENTS} onChange={setInstrument} />
                </div>
                <div>
                  <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '5px' }}>Min Holding (days)</label>
                  <input type="text" value={minHolding} onChange={(e) => setMinHolding(e.target.value)} style={{ width: '80px', background: 'var(--surface-input)', border: '1px solid var(--border-default)', borderRadius: '6px', padding: '7px 10px', font: 'var(--type-data)', color: 'var(--text-primary)', boxSizing: 'border-box' }} />
                </div>
              </div>
            </div>

            {/* Trade Style + Trend Params — CENTER (2-col grid) */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
              {/* Trade Style */}
              <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '12px 14px' }}>
                <h2 style={{ margin: '0 0 10px', font: 'var(--type-h3)', color: 'var(--text-primary)', fontSize: '12px' }}>Trade Style</h2>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {[{ key: 'mean-reversion', label: 'Mean-Reversion' }, { key: 'trend', label: 'Trend' }].map(({ key, label }) => (
                    <label key={key} style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', font: 'var(--type-label)', color: tradeStyle === key ? 'var(--text-primary)' : 'var(--text-muted)', fontSize: '10px' }}>
                      <div onClick={() => setTradeStyle(key)} style={{
                        width: '12px', height: '12px', borderRadius: '50%',
                        border: '2px solid ' + (tradeStyle === key ? accentAmber : 'var(--border-default)'),
                        background: tradeStyle === key ? accentAmber : 'transparent',
                        flexShrink: 0, cursor: 'pointer', transition: 'all 0.15s',
                      }}></div>
                      <span onClick={() => setTradeStyle(key)}>{label}</span>
                    </label>
                  ))}
                  {tradeStyle === 'trend' && (
                    <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', padding: '4px 6px', background: 'var(--surface-input)', borderRadius: '3px', border: '1px solid var(--border-default)', marginTop: '4px', fontSize: '8px', lineHeight: '1.2' }}>
                      Auto: <span style={{ color: accentAmber, fontWeight: 600 }}>UNCERTAIN</span> {'->'} <span style={{ color: accentAmber }}>Trend</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Trend Parameters */}
              {tradeStyle === 'trend' && (
                <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '12px 14px' }}>
                  <h2 style={{ margin: '0 0 10px', font: 'var(--type-h3)', color: 'var(--text-primary)', fontSize: '12px' }}>Trend</h2>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                    {[
                      { label: 'Theta', value: theta, set: setTheta },
                      { label: 'Mom w', value: momWindow, set: setMomWindow },
                      { label: 'Vol w', value: volWindow, set: setVolWindow },
                      { label: 'Trail', value: trailMult, set: setTrailMult },
                    ].map(({ label, value, set }) => (
                      <div key={label}>
                        <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '3px', fontSize: '8px' }}>{label}</label>
                        <Stepper value={value} onChange={set} />
                      </div>
                    ))}
                  </div>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', font: 'var(--type-label)', color: 'var(--text-secondary)', fontSize: '9px' }}>
                    <div onClick={() => setAllowShort(!allowShort)} style={{
                      width: '12px', height: '12px', borderRadius: '2px',
                      border: '2px solid ' + (allowShort ? accentAmber : 'var(--border-default)'),
                      background: allowShort ? accentAmber : 'transparent',
                      flexShrink: 0, cursor: 'pointer', transition: 'all 0.15s',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      {allowShort && <svg width="8" height="6" viewBox="0 0 9 7" fill="none"><path d="M1 3.5L3.5 6L8 1" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                    </div>
                    <span onClick={() => setAllowShort(!allowShort)}>Allow short</span>
                  </label>
                </div>
              )}
            </div>
          </div>

          {/* Run Button */}
          <div>
            <button style={{ padding: '10px 20px', font: 'var(--type-label)', background: accentAmber, color: 'var(--text-on-accent)', border: 'none', borderRadius: '6px', cursor: 'pointer', transition: 'filter 0.15s' }}
              onMouseEnter={(e) => e.target.style.filter = 'brightness(1.1)'}
              onMouseLeave={(e) => e.target.style.filter = 'brightness(1)'}
            >▶ Run Individual Backtest</button>
          </div>

          {/* Results */}
          {showResults && (
            <>
              {/* Performance KPI Cards Grid — Enlarged Separate Boxes */}
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: '12px' }}>
                {[
                  { label: 'Total Trades', value: MOCK_INDIVIDUAL.totalTrades, color: 'var(--text-primary)' },
                  { label: 'Win Rate', value: MOCK_INDIVIDUAL.winRate + '%', color: 'var(--negative)' },
                  { label: 'Total PnL', value: MOCK_INDIVIDUAL.totalPnl + ' bp', color: 'var(--negative)' },
                  { label: 'Avg PnL', value: MOCK_INDIVIDUAL.avgPnl + ' bp', color: 'var(--negative)' },
                  { label: 'Avg Hold', value: MOCK_INDIVIDUAL.avgHold + ' days', color: 'var(--text-primary)' },
                  { label: 'Sharpe', value: MOCK_INDIVIDUAL.sharpe, color: 'var(--negative)' },
                  { label: 'Max DD', value: MOCK_INDIVIDUAL.maxDD + ' bp', color: accentAmber },
                ].map((kpi, i) => (
                  <div key={i} style={{
                    background: 'var(--surface-panel)',
                    border: '1px solid var(--border-strong)',
                    borderRadius: '8px',
                    padding: '12px 8px',
                    textAlign: 'center',
                  }}>
                    <div style={{ font: 'var(--type-label)', color: 'var(--text-muted)', marginBottom: '6px', fontSize: '10px' }}>
                      {kpi.label}
                    </div>
                    <div style={{ font: 'var(--type-data)', color: kpi.color, lineHeight: 1.2, fontWeight: 600, fontSize: '12px' }}>
                      {kpi.value}
                    </div>
                  </div>
                ))}
              </div>

              {/* Instrument History Chart */}
              <div style={{border:'1px solid var(--border-strong)',borderRadius:'8px',overflow:'hidden'}}>
                <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',padding:'11px 16px',background:'var(--surface-panel)',borderBottom:'1px solid var(--border-strong)',userSelect:'none'}}>
                  <div style={{display:'flex',alignItems:'center',gap:'10px'}}>
                    <span style={{font:'var(--type-h2)',fontSize:'13px',fontWeight:600,color:'var(--text-primary)'}}>Instrument History</span>
                  </div>
                </div>
                <div style={{padding:'12px 16px',display:'flex',gap:'12px',font:'var(--type-meta)',fontSize:'8px',color:'var(--text-muted)',borderBottom:'1px solid var(--border-strong)'}}>
                  {[['#38bdf8','Spread Price'],[accentAmber,'CRR Level'],[' #34d399','Exit (Profit)'],['#f87171','Entry (Loss)']].map(([c,l])=>(
                    <span key={l} style={{display:'flex',alignItems:'center',gap:'4px'}}>
                      <span style={{width:'12px',height:'2px',background:c,display:'inline-block',borderRadius:'1px'}}></span>{l}
                    </span>
                  ))}
                </div>
                <div style={{padding:'12px 16px'}}>
                  {(() => {
                    const W=900,H=180,pad={t:12,b:24,l:36,r:12};
                    const iw=W-pad.l-pad.r,ih=H-pad.t-pad.b;
                    // Generate synthetic instrument history data
                    const N=80;
                    let instrumentTS=[];
                    let v=22;
                    for(let i=0;i<N;i++){v+=(Math.random()-0.5)*1.2+0.05;instrumentTS.push(Math.max(10,v));}
                    const crrLevel=instrumentTS.map(()=>18);
                    const allVals=[...instrumentTS,...crrLevel];
                    const mn=Math.min(...allVals)-1,mx=Math.max(...allVals)+1,rng=mx-mn||1;
                    const px=i=>pad.l+i*(iw/(N-1));
                    const py=v=>pad.t+ih-(((v-mn)/rng)*ih);
                    const months=['Aug 25','Oct 25','Dec 25','Feb 26','Apr 26','Jun 26'];
                    const step=Math.floor(N/5);
                    const makePath=data=>data.map((v,i)=>`${i===0?'M':'L'}${px(i)},${py(v)}`).join(' ');
                    
                    return (
                      <svg width="100%" viewBox={`0 0 ${W} ${H}`} style={{display:'block'}}>
                        {[0,0.25,0.5,0.75,1].map(t=>(
                          <line key={t} x1={pad.l} x2={W-pad.r} y1={pad.t+ih*t} y2={pad.t+ih*t} stroke="rgba(255,255,255,0.06)" strokeWidth="1"/>
                        ))}
                        <path d={makePath(crrLevel)} fill="none" stroke={accentAmber} strokeWidth="1.2" strokeDasharray="5,3" opacity="0.7"/>
                        <path d={makePath(instrumentTS)} fill="none" stroke="#38bdf8" strokeWidth="2" opacity="0.9"/>
                        {/* Entry/Exit markers */}
                        <circle cx={px(12)} cy={py(instrumentTS[12])} r="4" fill="none" stroke="#f87171" strokeWidth="1.5"/>
                        <circle cx={px(28)} cy={py(instrumentTS[28])} r="4" fill="#34d399"/>
                        <circle cx={px(52)} cy={py(instrumentTS[52])} r="4" fill="none" stroke="#f87171" strokeWidth="1.5"/>
                        <circle cx={px(68)} cy={py(instrumentTS[68])} r="4" fill="#34d399"/>
                        {[0,0.25,0.5,0.75,1].map(t=>{
                          const v=(mn+rng*t).toFixed(0);
                          return <text key={t} x={pad.l-4} y={pad.t+ih*(1-t)+3} textAnchor="end" fill="rgba(255,255,255,0.35)" fontSize="8">{v}</text>;
                        })}
                        {months.map((l,i)=>(
                          <text key={i} x={px(i*step)} y={H-6} textAnchor="middle" fill="rgba(255,255,255,0.3)" fontSize="8">{l}</text>
                        ))}
                      </svg>
                    );
                  })()}
                </div>
              </div>
            </>
          )}
        </>
      )}

      {/* ── PORTFOLIO MODE ── */}
      {mode === 'portfolio' && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr auto', gap: '14px', alignItems: 'start' }}>

            {/* Portfolio Data — LEFT */}
            <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '14px 16px', minWidth: '240px', maxWidth: '300px' }}>
              <h2 style={{ margin: '0 0 10px', font: 'var(--type-h3)', color: 'var(--text-primary)' }}>Portfolio Data</h2>
              {/* Stats row */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginBottom: '12px' }}>
                {[
                  { label: 'Total Assets', value: '16', color: accentAmber },
                  { label: 'Weight Sum', value: '94.7%', color: 'var(--text-primary)' },
                  { label: 'Direction', value: 'BUY: 16 / SELL: 0', color: 'var(--text-primary)' },
                  { label: 'Styles', value: 'MR: 10 | Mom: 6', color: 'var(--text-primary)' },
                ].map((s, i) => (
                  <div key={i}>
                    <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginBottom: '2px' }}>{s.label}</div>
                    <div style={{ font: 'var(--type-data)', color: s.color, fontSize: '11px' }}>{s.value}</div>
                  </div>
                ))}
              </div>
              {/* Asset list */}
              <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginBottom: '6px' }}>Active Portfolio Assets (Backtest Universe):</div>
              <div style={{ maxHeight: '180px', overflowY: 'auto', border: '1px solid var(--border-default)', borderRadius: '4px', padding: '6px 10px', background: 'var(--surface-input)' }}>
                {PORTFOLIO_ASSETS.map((a, i) => (
                  <div key={i} style={{ font: 'var(--type-meta)', color: 'var(--text-secondary)', padding: '3px 0', display: 'flex', gap: '6px' }}>
                    <span style={{ color: 'var(--text-muted)' }}>•</span>
                    <span>{a.name} {'-'} {a.weight}</span>
                    <span style={{ color: accentAmber, fontWeight: 600 }}>({a.dir})</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Backtest Settings — MIDDLE */}
            <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '14px 16px' }}>
              <h2 style={{ margin: '0 0 12px', font: 'var(--type-h3)', color: 'var(--text-primary)' }}>Backtest Settings</h2>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '12px' }}>
                <div>
                  <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Backtest Period</label>
                  <Dropdown value={backtestPeriod} options={BACKTEST_PERIODS} onChange={setBacktestPeriod} />
                </div>
                <div>
                  <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Initial Capital (MM)</label>
                  <input type="text" value={initialCapital} onChange={(e) => setInitialCapital(e.target.value)} style={{ width: '100%', background: 'var(--surface-input)', border: '1px solid var(--border-default)', borderRadius: '6px', padding: '8px 10px', font: 'var(--type-data)', color: 'var(--text-primary)', boxSizing: 'border-box' }} />
                </div>
                <div>
                  <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Transaction Cost (bp)</label>
                  <input type="text" value={txCost} onChange={(e) => setTxCost(e.target.value)} style={{ width: '100%', background: 'var(--surface-input)', border: '1px solid var(--border-default)', borderRadius: '6px', padding: '8px 10px', font: 'var(--type-data)', color: 'var(--text-primary)', boxSizing: 'border-box' }} />
                </div>
                <div>
                  <label style={{ font: 'var(--type-label)', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>Date Mode</label>
                  <div style={{ display: 'flex', gap: '4px', background: 'var(--surface-input)', padding: '4px', borderRadius: '6px', border: '1px solid var(--border-default)' }}>
                    {['preset', 'custom'].map(m => (
                      <button key={m} onClick={() => setDateMode(m)} style={{
                        flex: 1, padding: '6px 10px', font: 'var(--type-label)', border: 'none', borderRadius: '4px', cursor: 'pointer',
                        background: dateMode === m ? accentAmber : 'transparent',
                        color: dateMode === m ? 'var(--text-on-accent)' : 'var(--text-muted)',
                        transition: 'all 0.15s', fontSize: '10px',
                      }}
                      onMouseEnter={(e) => { if (dateMode !== m) e.target.style.background = accentAmberSoft; }}
                      onMouseLeave={(e) => { if (dateMode !== m) e.target.style.background = 'transparent'; }}
                      >{m === 'preset' ? 'Preset' : 'Custom'}</button>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Actions — RIGHT */}
            <div style={{ background: 'var(--surface-panel)', border: '1px solid var(--border-strong)', borderRadius: '6px', padding: '14px 16px', minWidth: '140px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <h2 style={{ margin: '0', font: 'var(--type-h3)', color: 'var(--text-primary)', fontSize: '12px' }}>Actions</h2>
              <button style={{ padding: '10px 12px', font: 'var(--type-label)', background: accentAmber, color: 'var(--text-on-accent)', border: 'none', borderRadius: '6px', cursor: 'pointer', transition: 'filter 0.15s', fontSize: '10px' }}
                onMouseEnter={(e) => e.target.style.filter = 'brightness(1.1)'}
                onMouseLeave={(e) => e.target.style.filter = 'brightness(1)'}
              >▶ Run Portfolio Backtest</button>
              <button style={{ padding: '10px 12px', font: 'var(--type-label)', background: accentAmberSoft, color: accentAmber, border: '1px solid ' + accentAmber, borderRadius: '6px', cursor: 'pointer', transition: 'all 0.15s', fontSize: '10px' }}
                onMouseEnter={(e) => e.target.style.background = 'rgba(224,162,60,0.25)'}
                onMouseLeave={(e) => e.target.style.background = accentAmberSoft}
              >Generate Report</button>
              <button style={{ padding: '10px 12px', font: 'var(--type-label)', background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border-default)', borderRadius: '6px', cursor: 'pointer', transition: 'all 0.15s', fontSize: '10px' }}
                onMouseEnter={(e) => { e.target.style.borderColor = 'var(--border-strong)'; e.target.style.color = 'var(--text-primary)'; }}
                onMouseLeave={(e) => { e.target.style.borderColor = 'var(--border-default)'; e.target.style.color = 'var(--text-muted)'; }}
              >Download</button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

window.BacktestAlpha = BacktestAlpha;
