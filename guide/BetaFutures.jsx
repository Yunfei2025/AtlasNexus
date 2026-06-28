// Beta Book > Futures — AlphaVolatility-consistent layout
const _ns_bfut = window.AtlasNexusDesignSystem_988df3;

const SYMBOLS = ['TL.CFE','T.CFE','TF.CFE','TS.CFE','IF.CFE','IC.CFE'];
const IN_SAMPLES = ['6M','1 Yr','2 Yr','3 Yr'];
const STRATEGIES_LIST = [
  { key:'MA',        label:'MA',         checked:true  },
  { key:'Bollinger', label:'Bollinger',  checked:true  },
  { key:'Momentum',  label:'Momentum',   checked:false },
  { key:'SAR',       label:'SAR',        checked:true  },
  { key:'DeMark',    label:'DeMark',     checked:false },
  { key:'VWAP',      label:'VWAP',       checked:false },
  { key:'ATR',       label:'ATR',        checked:false },
  { key:'MktRegime', label:'Mkt Regime', checked:true  },
];

const CANDLES = [
  { d:'May 27', o:113.62, h:113.70, l:113.58, c:113.60 },
  { d:'May 28', o:113.60, h:114.00, l:113.55, c:113.95 },
  { d:'May 29', o:113.95, h:114.10, l:113.72, c:113.75 },
  { d:'May 30', o:113.75, h:114.32, l:113.70, c:114.20 },
  { d:'Jun 2',  o:114.20, h:114.30, l:114.05, c:114.22 },
  { d:'Jun 3',  o:114.22, h:114.28, l:114.00, c:114.10 },
  { d:'Jun 4',  o:114.10, h:114.18, l:113.95, c:114.00 },
  { d:'Jun 5',  o:114.00, h:114.40, l:113.98, c:114.35 },
  { d:'Jun 6',  o:114.35, h:114.45, l:114.05, c:114.12 },
  { d:'Jun 8',  o:114.12, h:114.15, l:113.72, c:113.78 },
  { d:'Jun 9',  o:113.78, h:113.85, l:113.60, c:113.65 },
  { d:'Jun 10', o:113.65, h:113.70, l:113.42, c:113.48 },
  { d:'Jun 11', o:113.48, h:113.52, l:113.05, c:113.10 },
  { d:'Jun 12', o:113.10, h:113.35, l:113.08, c:113.28 },
  { d:'Jun 13', o:113.28, h:113.45, l:113.22, c:113.42 },
  { d:'Jun 14', o:113.42, h:113.65, l:113.38, c:113.60 },
  { d:'Jun 16', o:113.60, h:113.72, l:113.52, c:113.68 },
];

const MA_EQ   = [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1];
const BOLL_EQ = [1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1,1];
const SAR_EQ  = [1,0.9988,0.9975,0.9970,0.9965,0.9960,0.9958,0.9954,0.9950,0.9947,0.9942,0.9937,0.9930,0.9923,0.9918,0.9915,0.9908];

const STRAT_STATS = [
  { key:'MA',   label:'MA',         ret:'0.00%',  dd:'0.00%',  sharpe: 0.00, trades:0, retPos:false, ddPos:true  },
  { key:'Boll', label:'Bollinger',  ret:'0.00%',  dd:'0.00%',  sharpe: 0.00, trades:0, retPos:false, ddPos:true  },
  { key:'SAR',  label:'SAR',        ret:'-0.98%', dd:'-1.16%', sharpe:-5.74, trades:3, retPos:false, ddPos:false },
];

function BetaFutures() {
  const { useState } = React;
  const [source, setSource]     = useState('Local');
  const [mode, setMode]         = useState('Daily');
  const [symbol, setSymbol]     = useState('TL.CFE');
  const [startDate, setStartDate] = useState('2026-05');
  const [endDate, setEndDate]   = useState('2026-06');
  const [oosDate, setOosDate]   = useState('2026-06');
  const [inSample, setInSample] = useState('1 Yr');
  const [strategies, setStrategies] = useState(
    () => Object.fromEntries(STRATEGIES_LIST.map(s => [s.key, s.checked]))
  );
  const [trending, setTrending] = useState('SAR');
  const [meanRev, setMeanRev]   = useState('Boll');
  const [maShort, setMaShort]   = useState('5');
  const [maLong, setMaLong]     = useState('20');
  const [expandedParams, setExpandedParams] = useState({ MA:true });
  const [hasResults, setHasResults] = useState(true);

  const accentBlue = 'var(--accent-blue)';
  const amber      = 'var(--accent-amber)';

  const toggleStrategy = k => setStrategies(s => ({ ...s, [k]: !s[k] }));
  const toggleParam    = k => setExpandedParams(e => ({ ...e, [k]: !e[k] }));

  function CardHeader({ title, badge }) {
    return (
      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'11px 16px',
        background:'var(--surface-panel)', borderBottom:'1px solid var(--border-strong)', userSelect:'none' }}>
        <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
          <span style={{ font:'var(--type-h2)', fontSize:'13px', fontWeight:600, color:'var(--text-primary)' }}>{title}</span>
          {badge && <span style={{ font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)',
            background:'var(--surface-input)', padding:'2px 7px', borderRadius:'3px', border:'1px solid var(--border-default)' }}>{badge}</span>}
        </div>
      </div>
    );
  }

  const Radio = ({ val, cur, set, label }) => (
    <label style={{ display:'flex', alignItems:'center', gap:'4px', cursor:'pointer',
      font:'var(--type-label)', fontSize:'10px', color: cur===val ? 'var(--text-primary)' : 'var(--text-muted)' }}>
      <div onClick={() => set(val)} style={{ width:'10px', height:'10px', borderRadius:'50%', flexShrink:0, cursor:'pointer',
        border:'2px solid ' + (cur===val ? accentBlue : 'var(--border-strong)'),
        background: cur===val ? accentBlue : 'transparent' }}></div>
      <span onClick={() => set(val)}>{label}</span>
    </label>
  );

  const Checkbox = ({ checked, onChange, label }) => (
    <label style={{ display:'flex', alignItems:'center', gap:'5px', cursor:'pointer',
      font:'var(--type-label)', fontSize:'10px', color: checked ? 'var(--text-primary)' : 'var(--text-muted)' }}>
      <div onClick={onChange} style={{ width:'11px', height:'11px', borderRadius:'2px', flexShrink:0, cursor:'pointer',
        border:'2px solid ' + (checked ? accentBlue : 'var(--border-strong)'),
        background: checked ? accentBlue : 'transparent',
        display:'flex', alignItems:'center', justifyContent:'center' }}>
        {checked && <svg width="7" height="5" viewBox="0 0 8 6" fill="none"><path d="M1 3L3 5L7 1" stroke="#fff" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>}
      </div>
      <span onClick={onChange}>{label}</span>
    </label>
  );

  const Stepper = ({ value, onChange }) => (
    <div style={{ display:'flex', alignItems:'center', border:'1px solid var(--border-default)', borderRadius:'4px',
      overflow:'hidden', background:'var(--surface-input)' }}>
      <button onClick={() => onChange(String(Math.max(1,(parseInt(value)||0)-1)))} style={{ width:'22px', height:'26px', border:'none',
        background:'transparent', color:'var(--text-muted)', cursor:'pointer', fontSize:'14px', borderRight:'1px solid var(--border-default)' }}>−</button>
      <input value={value} onChange={e => onChange(e.target.value)} style={{ width:'36px', border:'none',
        background:'transparent', font:'var(--type-data)', fontSize:'11px', color:'var(--text-primary)', textAlign:'center', padding:'0' }}/>
      <button onClick={() => onChange(String((parseInt(value)||0)+1))} style={{ width:'22px', height:'26px', border:'none',
        background:'transparent', color:'var(--text-muted)', cursor:'pointer', fontSize:'14px', borderLeft:'1px solid var(--border-default)' }}>+</button>
    </div>
  );

  // Split candlestick + equity chart
  function BacktestChart() {
    const W = 800, H = 400;
    const priceH = 240, eqH = 120, sepY = priceH + 20;
    const padL = 44, padR = 8, padB = 24;

    const allP  = CANDLES.flatMap(c => [c.h, c.l]);
    const yMinP = Math.min(...allP) - 0.05;
    const yMaxP = Math.max(...allP) + 0.05;
    const rngP  = yMaxP - yMinP;

    const cw    = (W - padL - padR) / CANDLES.length;
    const cpx   = i => padL + i * cw + cw / 2;
    const cpy   = v => 8 + (priceH - 8) - ((v - yMinP) / rngP) * (priceH - 16);

    const allEq = [...MA_EQ, ...BOLL_EQ, ...SAR_EQ];
    const yMinE = Math.min(...allEq) - 0.001;
    const yMaxE = Math.max(...allEq) + 0.001;
    const rngE  = yMaxE - yMinE;
    const eqTop = sepY + 8;
    const eqBot = sepY + eqH - padB;
    const epy   = v => eqBot - ((v - yMinE) / rngE) * (eqBot - eqTop);

    function eqPath(series) {
      return series.map((v, i) => `${i===0?'M':'L'}${cpx(i).toFixed(1)},${epy(v).toFixed(1)}`).join(' ');
    }

    const priceTicks = [];
    const step = Math.ceil(rngP / 5 / 0.2) * 0.2;
    for (let v = Math.ceil(yMinP / 0.2) * 0.2; v <= yMaxP + 0.01; v = Math.round((v + step) * 100) / 100) {
      priceTicks.push(v);
    }

    const xLabels = CANDLES.filter((_, i) => i % 3 === 0);

    return (
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width:'100%', height:'auto', display:'block' }} preserveAspectRatio="xMidYMid meet">
        {/* Price grid */}
        {priceTicks.map((v, i) => (
          <g key={i}>
            <line x1={padL} y1={cpy(v)} x2={W - padR} y2={cpy(v)} stroke="rgba(100,140,200,0.1)" strokeWidth="0.8"/>
            <text x={padL - 4} y={cpy(v) + 3} textAnchor="end" fontSize="8" fill="rgba(150,180,220,0.6)">{v.toFixed(1)}</text>
          </g>
        ))}

        {/* Separator */}
        <line x1={padL} y1={sepY} x2={W - padR} y2={sepY} stroke="rgba(100,140,200,0.18)" strokeWidth="1" strokeDasharray="3,3"/>

        {/* Equity grid */}
        {[yMinE, (yMinE + yMaxE) / 2, yMaxE].map((v, i) => (
          <g key={i}>
            <line x1={padL} y1={epy(v)} x2={W - padR} y2={epy(v)} stroke="rgba(100,140,200,0.08)" strokeWidth="0.8"/>
            <text x={padL - 4} y={epy(v) + 3} textAnchor="end" fontSize="8" fill="rgba(150,180,220,0.6)">{v.toFixed(3)}</text>
          </g>
        ))}

        {/* Candlesticks */}
        {CANDLES.map((c, i) => {
          const bull  = c.c >= c.o;
          const color = bull ? '#4ade80' : '#f87171';
          const bTop  = cpy(Math.max(c.o, c.c));
          const bBot  = cpy(Math.min(c.o, c.c));
          const bH    = Math.max(bBot - bTop, 2);
          const x     = cpx(i);
          const bw    = cw * 0.52;
          return (
            <g key={i}>
              <line x1={x} y1={cpy(c.h)} x2={x} y2={cpy(c.l)} stroke={color} strokeWidth="1.1" opacity="0.85"/>
              <rect x={x - bw / 2} y={bTop} width={bw} height={bH} fill={color} opacity="0.82" rx="0.5"/>
            </g>
          );
        })}

        {/* Equity lines */}
        <path d={eqPath(MA_EQ)}   fill="none" stroke="#f87171" strokeWidth="1.5" opacity="0.85"/>
        <path d={eqPath(BOLL_EQ)} fill="none" stroke="#34d399" strokeWidth="1.5" opacity="0.85"/>
        <path d={eqPath(SAR_EQ)}  fill="none" stroke="#c084fc" strokeWidth="1.5" opacity="0.85"/>

        {/* X-axis labels */}
        {xLabels.map((c, i) => {
          const idx = CANDLES.indexOf(c);
          return (
            <text key={i} x={cpx(idx)} y={H - 4} textAnchor="middle" fontSize="8" fill="rgba(150,180,220,0.6)">{c.d}</text>
          );
        })}

        {/* Panel labels */}
        <text x={padL + 6} y={22} fontSize="9" fill="rgba(150,180,220,0.5)" fontWeight="500">Price</text>
        <text x={padL + 6} y={eqTop + 14} fontSize="9" fill="rgba(150,180,220,0.5)" fontWeight="500">Equity</text>
      </svg>
    );
  }

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'10px' }}>

      {/* Page title */}
      <div>
        <h1 style={{ margin:'0 0 3px', font:'var(--type-h1)', color:'var(--text-primary)' }}>Futures Strategy Backtest</h1>
        <div style={{ font:'var(--type-meta)', color:'var(--text-muted)' }}>Backtest configuration · strategy comparison · price &amp; equity</div>
      </div>

      {/* Top 3-col row */}
      <div style={{ display:'grid', gridTemplateColumns:'220px 1fr 1fr', gap:'10px', alignItems:'start' }}>

        {/* ── Controls ── */}
        <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
          <CardHeader title="Controls" />
          <div style={{ padding:'12px 14px', display:'flex', flexDirection:'column', gap:'10px' }}>

            {/* Source */}
            <div>
              <div style={{ font:'var(--type-label)', fontSize:'9px', color:accentBlue, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'6px' }}>Data</div>
              <div style={{ display:'flex', gap:'10px', marginBottom:'5px' }}>
                <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'10px', width:'38px' }}>Source</span>
                <Radio val="Local" cur={source} set={setSource} label="Local"/>
                <Radio val="Wind"  cur={source} set={setSource} label="Wind"/>
              </div>
              <div style={{ display:'flex', gap:'10px' }}>
                <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'10px', width:'38px' }}>Mode</span>
                <Radio val="Daily"    cur={mode} set={setMode} label="Daily"/>
                <Radio val="Intraday" cur={mode} set={setMode} label="Intraday"/>
              </div>
            </div>

            {/* Symbol */}
            <div style={{ display:'flex', flexDirection:'column', gap:'4px' }}>
              <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>Symbol</div>
              <select value={symbol} onChange={e => setSymbol(e.target.value)} style={{ padding:'6px 8px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', color:'var(--text-primary)', font:'var(--type-data)', fontSize:'11px', cursor:'pointer' }}>
                {SYMBOLS.map(s => <option key={s}>{s}</option>)}
              </select>
            </div>

            {/* Date range */}
            <div style={{ display:'flex', flexDirection:'column', gap:'4px' }}>
              <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>Date Range</div>
              <div style={{ display:'flex', alignItems:'center', gap:'4px' }}>
                <input type="month" value={startDate} onChange={e => setStartDate(e.target.value)} style={{ flex:1, background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 6px', font:'var(--type-data)', fontSize:'9px', color:'var(--text-primary)', colorScheme:'dark' }}/>
                <span style={{ color:'var(--text-muted)', fontSize:'10px' }}>→</span>
                <input type="month" value={endDate} onChange={e => setEndDate(e.target.value)} style={{ flex:1, background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 6px', font:'var(--type-data)', fontSize:'9px', color:'var(--text-primary)', colorScheme:'dark' }}/>
              </div>
            </div>

            {/* OOS / In-sample */}
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'6px' }}>
              <div style={{ display:'flex', flexDirection:'column', gap:'3px' }}>
                <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>OOS Split</div>
                <input type="month" value={oosDate} onChange={e => setOosDate(e.target.value)} style={{ background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 6px', font:'var(--type-data)', fontSize:'9px', color:'var(--text-primary)', colorScheme:'dark', width:'100%', boxSizing:'border-box' }}/>
              </div>
              <div style={{ display:'flex', flexDirection:'column', gap:'3px' }}>
                <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>In-sample</div>
                <select value={inSample} onChange={e => setInSample(e.target.value)} style={{ padding:'5px 6px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', color:'var(--text-primary)', font:'var(--type-data)', fontSize:'10px', cursor:'pointer' }}>
                  {IN_SAMPLES.map(s => <option key={s}>{s}</option>)}
                </select>
              </div>
            </div>

            {/* Strategies */}
            <div>
              <div style={{ font:'var(--type-label)', fontSize:'9px', color:accentBlue, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'6px' }}>Strategies</div>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'5px 8px' }}>
                {STRATEGIES_LIST.map(s => (
                  <Checkbox key={s.key} checked={!!strategies[s.key]} onChange={() => toggleStrategy(s.key)} label={s.label}/>
                ))}
              </div>
            </div>

            {/* Buttons */}
            <button onClick={() => setHasResults(true)} style={{ padding:'7px', font:'var(--type-label)', fontSize:'11px', fontWeight:700, background:'var(--positive)', color:'var(--navy-950)', border:'none', borderRadius:'4px', cursor:'pointer', width:'100%' }}>▶ Run Backtest</button>
            <button style={{ padding:'6px', font:'var(--type-label)', fontSize:'10px', background:'transparent', color:'var(--text-muted)', border:'1px solid var(--border-default)', borderRadius:'4px', cursor:'pointer', width:'100%' }}>↻ Refresh</button>
          </div>
        </div>

        {/* ── Strategy Performance ── */}
        <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
          <CardHeader title="Strategy Performance" badge={`${symbol} · ${mode}`} />
          <div style={{ overflowX:'auto' }}>
            <table style={{ width:'100%', borderCollapse:'collapse', font:'var(--type-data)', fontSize:'10px' }}>
              <thead>
                <tr style={{ background:'var(--surface-panel)', borderBottom:'1px solid var(--border-strong)' }}>
                  <th style={{ padding:'7px 12px', textAlign:'left', font:'var(--type-label)', fontSize:'8px', color:'var(--text-muted)', letterSpacing:'0.05em' }}>METRIC</th>
                  {STRAT_STATS.map(s => (
                    <th key={s.key} style={{ padding:'7px 12px', textAlign:'right', font:'var(--type-label)', fontSize:'8px', color:'var(--text-muted)', letterSpacing:'0.05em' }}>{s.label.toUpperCase()}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {[
                  { label:'Return',    key:'ret',    colorFn: (s) => s.retPos ? '#34d399' : '#f87171' },
                  { label:'Max DD',    key:'dd',     colorFn: (s) => s.ddPos  ? '#34d399' : '#f87171' },
                  { label:'Sharpe',    key:'sharpe', colorFn: (s) => s.sharpe >= 0 ? '#34d399' : '#f87171', fmt: v => typeof v==='number' ? v.toFixed(2) : v },
                  { label:'Trades',    key:'trades', colorFn: () => 'var(--text-secondary)' },
                ].map((row, i) => (
                  <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.04)', background: i%2===0 ? 'transparent' : 'rgba(255,255,255,0.015)' }}>
                    <td style={{ padding:'7px 12px', color:'var(--text-secondary)' }}>{row.label}</td>
                    {STRAT_STATS.map(s => (
                      <td key={s.key} style={{ padding:'7px 12px', textAlign:'right', fontWeight:600, color: row.colorFn(s) }}>
                        {row.fmt ? row.fmt(s[row.key]) : s[row.key]}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Legend strip */}
          <div style={{ padding:'8px 12px', borderTop:'1px solid var(--border-strong)', display:'flex', gap:'16px', flexWrap:'wrap' }}>
            {[['#f87171','MA Equity'],['#34d399','Boll Equity'],['#c084fc','SAR Equity']].map(([c, l]) => (
              <span key={l} style={{ display:'flex', alignItems:'center', gap:'5px', font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)' }}>
                <span style={{ width:'14px', height:'2px', background:c, display:'inline-block', borderRadius:'1px' }}></span>{l}
              </span>
            ))}
          </div>
        </div>

        {/* ── Regime & Parameters ── */}
        <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
          <CardHeader title="Regime &amp; Parameters" />
          <div style={{ padding:'12px 14px', display:'flex', flexDirection:'column', gap:'12px' }}>

            {/* Regime Logic */}
            <div>
              <div style={{ font:'var(--type-label)', fontSize:'9px', color:accentBlue, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>Regime Logic</div>
              <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'8px' }}>
                <div style={{ display:'flex', flexDirection:'column', gap:'3px' }}>
                  <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>Trending</div>
                  <select value={trending} onChange={e => setTrending(e.target.value)} style={{ padding:'6px 8px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', color:'var(--text-primary)', font:'var(--type-data)', fontSize:'10px', cursor:'pointer' }}>
                    {['SAR','MA','ATR'].map(s => <option key={s}>{s}</option>)}
                  </select>
                </div>
                <div style={{ display:'flex', flexDirection:'column', gap:'3px' }}>
                  <div style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.06em' }}>Mean-Rev</div>
                  <select value={meanRev} onChange={e => setMeanRev(e.target.value)} style={{ padding:'6px 8px', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', color:'var(--text-primary)', font:'var(--type-data)', fontSize:'10px', cursor:'pointer' }}>
                    {['Boll','MA','VWAP'].map(s => <option key={s}>{s}</option>)}
                  </select>
                </div>
              </div>
            </div>

            {/* Parameters */}
            <div>
              <div style={{ font:'var(--type-label)', fontSize:'9px', color:accentBlue, textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>Parameters</div>

              {/* MA */}
              <div style={{ marginBottom:'8px' }}>
                <div onClick={() => toggleParam('MA')} style={{ display:'flex', alignItems:'center', gap:'5px', cursor:'pointer', marginBottom: expandedParams.MA ? '8px' : '0' }}>
                  <span style={{ color:'var(--text-muted)', fontSize:'9px' }}>{expandedParams.MA ? '▼' : '▶'}</span>
                  <span style={{ font:'var(--type-label)', fontSize:'10px', color:'var(--text-secondary)', fontWeight:600 }}>MA</span>
                </div>
                {expandedParams.MA && (
                  <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'8px', paddingLeft:'12px' }}>
                    <div>
                      <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', marginBottom:'3px' }}>Short</div>
                      <Stepper value={maShort} onChange={setMaShort}/>
                    </div>
                    <div>
                      <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', marginBottom:'3px' }}>Long</div>
                      <Stepper value={maLong} onChange={setMaLong}/>
                    </div>
                  </div>
                )}
              </div>

              {['BOLLINGER','VWAP','MOMENTUM','ATR','SAR'].map(k => (
                <div key={k} onClick={() => toggleParam(k)} style={{ display:'flex', alignItems:'center', gap:'5px', cursor:'pointer', padding:'3px 0' }}>
                  <span style={{ color:'var(--text-muted)', fontSize:'9px' }}>{expandedParams[k] ? '▼' : '▶'}</span>
                  <span style={{ font:'var(--type-label)', fontSize:'10px', color:'var(--text-secondary)', fontWeight:600 }}>{k}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Full-width Backtest Results chart ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'11px 16px',
          background:'var(--surface-panel)', borderBottom:'1px solid var(--border-strong)' }}>
          <div style={{ display:'flex', alignItems:'center', gap:'10px' }}>
            <span style={{ font:'var(--type-h2)', fontSize:'13px', fontWeight:600, color:'var(--text-primary)' }}>Backtest Results</span>
            <span style={{ font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)', background:'var(--surface-input)',
              padding:'2px 7px', borderRadius:'3px', border:'1px solid var(--border-default)' }}>{symbol}</span>
          </div>
          {/* Legend */}
          <div style={{ display:'flex', gap:'14px', flexWrap:'wrap' }}>
            {[
              ['#4ade80','#f87171','Price'],
              ['#f87171', null, 'MA Equity'],
              ['#34d399', null, 'Boll Equity'],
              ['#c084fc', null, 'SAR Equity'],
            ].map(([c, c2, l]) => (
              <span key={l} style={{ display:'flex', alignItems:'center', gap:'4px', font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)' }}>
                {l === 'Price'
                  ? <><span style={{ width:'9px', height:'9px', background:c, display:'inline-block', borderRadius:'1px', opacity:0.85 }}></span><span style={{ width:'9px', height:'9px', background:c2, display:'inline-block', borderRadius:'1px', opacity:0.85 }}></span></>
                  : <span style={{ width:'14px', height:'2px', background:c, display:'inline-block', borderRadius:'1px' }}></span>
                }
                {l}
              </span>
            ))}
          </div>
        </div>

        <div style={{ padding:'12px 16px' }}>
          {!hasResults
            ? <div style={{ font:'var(--type-body)', color:'var(--text-muted)', fontSize:'10px', padding:'16px 0' }}>No results. Click ▶ Run Backtest to start.</div>
            : <BacktestChart/>
          }
        </div>
      </div>

    </div>
  );
}
window.BetaFutures = BetaFutures;
