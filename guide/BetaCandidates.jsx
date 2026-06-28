// Beta Book > Candidates — redesigned layout
const _ns_bb = window.AtlasNexusDesignSystem_988df3;

const SIGNAL_STATE = [
  { id:'IRDL.CN', signal:'Bullish',   z:'-0.23', scale:'0.5×', icir:'0.79', conf:'HIGH',   color:'#34d399', dir:'↑' },
  { id:'IRSL.CN', signal:'Flattener', z:'-1.05', scale:'1.1×', icir:'0.86', conf:'HIGH',   color:'#f87171', dir:'↓↓' },
  { id:'IRCV.CN', signal:'Neutral',   z:'+0.77', scale:'0.8×', icir:'1.34', conf:'HIGH',   color:'var(--text-muted)', dir:'‖' },
  { id:'FXDL.USDCNY', signal:'Neutral', z:'+1.47', scale:'1.5×', icir:'0.92', conf:'HIGH', color:'var(--text-muted)', dir:'‖' },
  { id:'CMDL.AU', signal:'Neutral',   z:'+1.38', scale:'1.4×', icir:'0.44', conf:'MEDIUM', color:'var(--text-muted)', dir:'‖' },
  { id:'CMDL.AL', signal:'Long',      z:'+1.42', scale:'1.4×', icir:'0.85', conf:'HIGH',   color:'#34d399', dir:'↑↑↑' },
];

const TOP_DRIVERS = {
  'IRDL.CN':     [['vs_IRCV_DE_20','0.091'], ['EMACross','0.076'], ['Mom252','0.048']],
  'IRSL.CN':     [['Mom60','0.124'], ['EMACrossLong','0.052'], ['Vol','0.031']],
  'IRCV.CN':     [['EMACrossLong','0.200'], ['ValueMom','-0.155'], ['vs_IRSL_DE_20','0.121']],
  'FXDL.USDCNY': [['vs_FXDL_GBPCNY_20','-0.136'], ['Mom60','-0.091'], ['Mom120','-0.045']],
  'CMDL.AU':     [['VolRatio','0.143'], ['Mem60','-0.101'], ['Vol60','-0.101']],
  'CMDL.AL':     [['Mom20','-0.216'], ['Mom10','-0.180'], ['Mom252','-0.090']],
};

const CORR_FACTORS = ['IRDL.CN','IRSL.CN','IRCV.CN','FXDL.USDCNY','CMDL.AU','CMDL.AL'];
const CORR_DATA = [
  ['IRDL.CN',  1.00, 0.12, 0.08, 0.05,-0.03,-0.07],
  ['IRSL.CN',  0.12, 1.00, 0.32, 0.15, 0.04, 0.06],
  ['IRCV.CN',  0.08, 0.32, 1.00, 0.55, 0.08, 0.04],
  ['FXDL.USDCNY', 0.05, 0.15, 0.55, 1.00,-0.26,-0.06],
  ['CMDL.AU', -0.03, 0.04, 0.08,-0.26, 1.00, 0.71],
  ['CMDL.AL', -0.07, 0.06, 0.04,-0.06, 0.71, 1.00],
];

const LOW_CORR_PAIRS = [
  ['IRDL.CN','CMDL.AL','-0.029'],
  ['IRSL.CN','FXDL.USDCNY','-0.085'],
  ['IRDL.CN','FXDL.USDCNY','-0.028'],
  ['IRCV.CN','CMDL.AU','0.037'],
  ['IRSL.CN','CMDL.AL','0.043'],
  ['IRSL.CN','CMDL.AU','-0.062'],
];

function getBetaCorr(a, b) {
  const ai = CORR_FACTORS.indexOf(a);
  const bi = CORR_FACTORS.indexOf(b);
  const rowIdx = Math.max(ai, bi);
  const colIdx = Math.min(ai, bi);
  if (rowIdx < 0 || colIdx < 0 || rowIdx >= CORR_DATA.length) return null;
  return CORR_DATA[rowIdx][colIdx + 1];
}

function betaCorrBg(v) {
  if (v === null) return 'transparent';
  const opacity = 0.18 + Math.abs(v) * 0.72;
  if (v > 0) return `rgba(30,80,160,${opacity})`;
  return `rgba(200,60,40,${opacity})`;
}

function BetaCandidates() {
  const { useState } = React;
  const [factors, setFactors] = useState({
    'CN-IRDL': true, 'CN-IRSL': true, 'CN-IRCV': true,
    'FXDL.USDCNY': true, 'CMDL.AU': true,
  });
  const [trainMonths, setTrainMonths] = useState('12');
  const [icThr, setIcThr]             = useState('0.05');
  const [topN, setTopN]               = useState('8');
  const [lookback, setLookback]       = useState('1 Year');
  const [topPairs, setTopPairs]       = useState('10');
  const [expandedCard, setExpandedCard] = useState(null);

  const toggle     = (k)  => setFactors(f => ({ ...f, [k]: !f[k] }));
  const toggleCard = (id) => setExpandedCard(prev => prev === id ? null : id);

  const domiciles    = ['CN','US','EU','JP','UK'];
  const domicileFlags = { CN:'🇨🇳', US:'🇺🇸', EU:'🇪🇺', JP:'🇯🇵', UK:'🇬🇧' };
  const irKinds = ['IRDL','IRSL','IRCV'];
  const fx = ['FXDL.USDCNY','FXDL.EURCNY','FXDL.JPYCNY','FXDL.GBPCNY'];
  const eq = [['EQDL.IF','CSI300'],['EQDL.IC','CSI 500'],['EQDL.IH','SSE 50'],['EQDL.IM','CSI 1000']];
  const cm = [
    ['CMDL.AU','Gold'],['CMDL.AG','Silver'],['CMDL.AL','Aluminum'],['CMDL.CU','Copper'],
    ['CMDL.ZN','Zinc'],['CMDL.SC','Crude Oil'],['CMDL.RB','Rebar'],['CMDL.LC','Live Hog'],
    ['CMDL.SA','Soda Ash'],['CMDL.JM','Coking Coal'],['CMDL.EC','Exch. Code'],
  ];

  const accentBlue = 'var(--accent-blue)';
  const confColor  = c => c === 'HIGH' ? '#34d399' : c === 'MEDIUM' ? 'var(--accent-amber)' : 'var(--text-muted)';

  const corrCols = CORR_FACTORS.slice(0, CORR_FACTORS.length - 1);
  const corrRows = CORR_FACTORS.slice(1);

  /* ── Sub-components ── */
  function SectionLabel({ children }) {
    return <div style={{ fontSize:'9px', fontWeight:600, color:'var(--text-muted)', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>{children}</div>;
  }

  function ShortSep() {
    return <div style={{ width:'1px', background:'var(--border-default)', alignSelf:'center', height:'75%', flexShrink:0, margin:'0 16px' }}></div>;
  }

  function CB({ k, label, sub }) {
    const checked = !!factors[k];
    return (
      <label style={{ display:'flex', alignItems:'center', gap:'7px', cursor:'pointer', userSelect:'none', padding:'3px 0' }}>
        <div onClick={() => toggle(k)} style={{ width:'13px', height:'13px', flexShrink:0, borderRadius:'3px', border:'1.5px solid '+(checked ? accentBlue : 'var(--border-strong)'), background: checked ? accentBlue : 'transparent', display:'flex', alignItems:'center', justifyContent:'center', cursor:'pointer', transition:'all 0.12s' }}>
          {checked && <svg width="8" height="8" viewBox="0 0 8 8"><polyline points="1,4 3,6 7,2" stroke="white" strokeWidth="1.8" fill="none"/></svg>}
        </div>
        <span onClick={() => toggle(k)} style={{ fontSize:'11px', color: checked ? 'var(--text-primary)' : 'var(--text-muted)', lineHeight:1.3 }}>
          {label}{sub && <span style={{ color:'var(--text-muted)', fontSize:'10px' }}> · {sub}</span>}
        </span>
      </label>
    );
  }

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:'12px' }}>
      <div>
        <h1 style={{ margin:'0 0 3px', font:'var(--type-h1)', color:'var(--text-primary)' }}>Beta Candidates</h1>
        <div style={{ font:'var(--type-meta)', color:'var(--text-muted)' }}>Factor selection, signal state, drivers, and correlations</div>
      </div>

      {/* ── SELECTION ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <div style={{ padding:'11px 16px', background:'var(--surface-panel)', borderBottom:'1px solid var(--border-strong)' }}>
          <span style={{ font:'var(--type-h2)', fontSize:'13px', fontWeight:600, color:'var(--text-primary)' }}>Selection</span>
        </div>

        <div style={{ padding:'14px 18px', display:'flex', alignItems:'stretch' }}>

          {/* Col 1: Interest Rates */}
          <div style={{ flexShrink:0 }}>
            <SectionLabel>Interest Rates</SectionLabel>
            <table style={{ borderCollapse:'collapse' }}>
              <thead>
                <tr>
                  <th style={{ minWidth:'40px' }}></th>
                  {domiciles.map(d => (
                    <th key={d} style={{ textAlign:'center', padding:'0 6px 6px', lineHeight:1 }}>
                      <div style={{ fontSize:'16px', lineHeight:1 }}>{domicileFlags[d]}</div>
                      <div style={{ fontSize:'9px', color:'var(--text-muted)', fontWeight:500, marginTop:'2px' }}>{d}</div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {irKinds.map(k => (
                  <tr key={k}>
                    <td style={{ fontSize:'11px', fontWeight:600, color:'var(--text-secondary)', paddingRight:'10px', paddingTop:'6px', paddingBottom:'6px', whiteSpace:'nowrap' }}>{k}</td>
                    {domiciles.map(d => {
                      const key = `${d}-${k}`;
                      const checked = !!factors[key];
                      return (
                        <td key={d} style={{ textAlign:'center', padding:'6px' }}>
                          <div onClick={() => toggle(key)} style={{ width:'13px', height:'13px', margin:'0 auto', borderRadius:'3px', border:'1.5px solid '+(checked ? accentBlue : 'var(--border-strong)'), background: checked ? accentBlue : 'transparent', cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'center', transition:'all 0.12s' }}>
                            {checked && <svg width="8" height="8" viewBox="0 0 8 8"><polyline points="1,4 3,6 7,2" stroke="white" strokeWidth="1.8" fill="none"/></svg>}
                          </div>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ShortSep />

          {/* Col 2: FX */}
          <div style={{ flexShrink:0 }}>
            <SectionLabel>FX</SectionLabel>
            <div style={{ display:'flex', flexDirection:'column' }}>
              {fx.map(k => <CB key={k} k={k} label={k.replace('FXDL.','')} />)}
            </div>
          </div>

          <ShortSep />

          {/* Col 3: Equities */}
          <div style={{ flexShrink:0 }}>
            <SectionLabel>Equities</SectionLabel>
            <div style={{ display:'flex', flexDirection:'column' }}>
              {eq.map(([k, desc]) => <CB key={k} k={k} label={k.replace('EQDL.','')} sub={desc} />)}
            </div>
          </div>

          <ShortSep />

          {/* Col 4: Commodities */}
          <div style={{ flex:1, minWidth:0 }}>
            <SectionLabel>Commodities</SectionLabel>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', columnGap:'4px' }}>
              {cm.map(([k, desc]) => <CB key={k} k={k} label={k.replace('CMDL.','')} sub={desc} />)}
            </div>
          </div>

          {/* Full-height separator before Train Params */}
          <div style={{ width:'1px', background:'var(--border-strong)', margin:'0 20px', flexShrink:0 }}></div>

          {/* Train Params */}
          <div style={{ width:'230px', flexShrink:0, display:'flex', flexDirection:'column', gap:'10px' }}>
            <SectionLabel>Train Params</SectionLabel>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr 1fr', gap:'6px' }}>
              {[['Months', trainMonths, setTrainMonths], ['IC Thr', icThr, setIcThr], ['Top N', topN, setTopN]].map(([lbl, val, setter]) => (
                <div key={lbl}>
                  <div style={{ fontSize:'9px', fontWeight:600, color:'var(--text-muted)', marginBottom:'4px' }}>{lbl}</div>
                  <input value={val} onChange={e => setter(e.target.value)} style={{ width:'100%', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 4px', fontSize:'11px', color:'var(--text-primary)', textAlign:'center', boxSizing:'border-box' }} />
                </div>
              ))}
            </div>
            <div style={{ display:'flex', gap:'6px' }}>
              <button style={{ flex:1, padding:'7px 0', background:'var(--accent-purple)', color:'#fff', border:'none', borderRadius:'5px', fontSize:'11px', fontWeight:700, cursor:'pointer' }}>Train</button>
              <button style={{ flex:1, padding:'7px 0', background:accentBlue, color:'#fff', border:'none', borderRadius:'5px', fontSize:'11px', fontWeight:700, cursor:'pointer' }}>Predict</button>
            </div>
            <div style={{ borderTop:'1px solid var(--border-default)', paddingTop:'8px', fontSize:'9px', color:'var(--text-muted)', lineHeight:1.55 }}>
              Train the factor model on data up to the first day of the current month (no recent daily data — reduces overfitting). Outputs the latest signal state and top driving indicators.
            </div>
            <div style={{ fontSize:'9px', color:'var(--accent-purple)', lineHeight:1.55 }}>
              🔮 Predicted from saved model through 20260531 (no retrain — all 6 factors already trained).
            </div>
          </div>
        </div>
      </div>

      {/* ── SIGNAL STATE + CORR MATRIX (side by side) ── */}
      <div style={{ border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', padding:'11px 16px', background:'var(--surface-panel)', borderBottom:'1px solid var(--border-strong)' }}>
          <span style={{ font:'var(--type-h2)', fontSize:'13px', fontWeight:600, color:'var(--text-primary)' }}>Current Signal State</span>
          <span style={{ font:'var(--type-meta)', fontSize:'9px', color:'var(--text-muted)', background:'var(--surface-input)', padding:'2px 7px', borderRadius:'3px', border:'1px solid var(--border-default)' }}>Mean ICIR: 0.87</span>
        </div>

        <div style={{ display:'flex', alignItems:'flex-start' }}>

          {/* Left: signal cards + lowest correlations */}
          <div style={{ flex:1, minWidth:0, borderRight:'1px solid var(--border-strong)', display:'flex', flexDirection:'column' }}>

            {/* Signal cards grid */}
            <div style={{ padding:'12px 16px', display:'grid', gridTemplateColumns:'repeat(3, 1fr)', gap:'8px' }}>
              {SIGNAL_STATE.map((s, i) => {
                const isOpen  = expandedCard === s.id;
                const drivers = TOP_DRIVERS[s.id] || [];
                const maxIC   = Math.max(...drivers.map(([, ic]) => Math.abs(parseFloat(ic))));
                return (
                  <div
                    key={i}
                    onClick={() => toggleCard(s.id)}
                    style={{ border:`2px solid ${isOpen ? 'var(--accent-blue)' : s.color}`, borderRadius:'6px', background:'var(--surface-input)', cursor:'pointer', transition:'border-color 0.15s', overflow:'hidden' }}
                  >
                    <div style={{ padding:'10px 12px' }}>
                      <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'4px' }}>
                        <span style={{ font:'var(--type-label)', fontSize:'9px', color:'var(--text-muted)' }}>{s.id}</span>
                        <svg width="10" height="10" viewBox="0 0 10 10" style={{ transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition:'transform 0.2s', flexShrink:0, opacity:0.5 }}>
                          <polyline points="2,3.5 5,6.5 8,3.5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      </div>
                      <div style={{ font:'var(--type-data)', fontSize:'13px', fontWeight:700, color:s.color, marginBottom:'6px' }}>{s.dir} {s.signal}</div>
                      <div style={{ display:'flex', flexDirection:'column', gap:'2px' }}>
                        {[['Signal Z', s.z], ['Scale', s.scale], ['ICIR', s.icir]].map(([lbl, val]) => (
                          <div key={lbl} style={{ display:'flex', justifyContent:'space-between', font:'var(--type-meta)', fontSize:'9px' }}>
                            <span style={{ color:'var(--text-muted)' }}>{lbl}</span>
                            <span style={{ color:'var(--text-secondary)' }}>{val}</span>
                          </div>
                        ))}
                        <div style={{ display:'flex', justifyContent:'space-between', font:'var(--type-meta)', fontSize:'9px', marginTop:'2px' }}>
                          <span style={{ color:'var(--text-muted)' }}>Conf</span>
                          <span style={{ color: confColor(s.conf), fontWeight:700 }}>{s.conf}</span>
                        </div>
                      </div>
                    </div>
                    {isOpen && drivers.length > 0 && (
                      <div style={{ borderTop:'1px solid var(--border-strong)', padding:'8px 12px 10px', background:'var(--surface-panel)' }}>
                        <div style={{ fontSize:'8px', color:'var(--accent-blue)', textTransform:'uppercase', letterSpacing:'0.07em', marginBottom:'7px' }}>Top Drivers</div>
                        {drivers.map(([feat, ic], di) => {
                          const icNum  = parseFloat(ic);
                          const isPos  = icNum >= 0;
                          const barPct = (Math.abs(icNum) / (maxIC || 1)) * 100;
                          return (
                            <div key={di} style={{ marginBottom: di < drivers.length - 1 ? '7px' : 0 }}>
                              <div style={{ display:'flex', justifyContent:'space-between', fontSize:'9px', marginBottom:'3px' }}>
                                <span style={{ color:'var(--text-secondary)' }}>{feat}</span>
                                <span style={{ color: isPos ? '#34d399' : '#f87171', fontWeight:600 }}>{isPos ? '+' : ''}{ic}</span>
                              </div>
                              <div style={{ height:'3px', borderRadius:'2px', background:'var(--border-strong)', overflow:'hidden' }}>
                                <div style={{ height:'100%', width: barPct+'%', background: isPos ? '#34d399' : '#f87171', borderRadius:'2px', opacity:0.8 }} />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Lowest Absolute Correlations — below signal cards */}
            <div style={{ borderTop:'1px solid var(--border-strong)', padding:'12px 16px' }}>
              <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between', marginBottom:'10px' }}>
                <span style={{ fontSize:'12px', fontWeight:600, color:'var(--text-primary)' }}>Lowest Absolute Correlations</span>
                <button style={{ padding:'4px 10px', background:'var(--accent-green)', color:'#fff', border:'none', borderRadius:'4px', fontSize:'9px', fontWeight:700, cursor:'pointer' }}>+ Add Assets</button>
              </div>
              <table style={{ width:'100%', borderCollapse:'collapse', fontSize:'10px' }}>
                <thead>
                  <tr style={{ borderBottom:'1px solid var(--border-strong)' }}>
                    {['Factor A','Factor B','Correlation'].map(h => (
                      <th key={h} style={{ padding:'4px 0', textAlign: h==='Correlation' ? 'right' : 'left', color:'var(--text-muted)', fontWeight:500 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {LOW_CORR_PAIRS.map(([a, b, corr], i) => (
                    <tr key={i} style={{ borderBottom:'1px solid rgba(255,255,255,0.04)' }}>
                      <td style={{ padding:'5px 0', color:accentBlue }}>{a}</td>
                      <td style={{ padding:'5px 0', color:accentBlue }}>{b}</td>
                      <td style={{ padding:'5px 0', textAlign:'right', color:'var(--text-secondary)' }}>{corr}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Right: Rank Correlation Matrix — lower triangle */}
          <div style={{ flexShrink:0, minWidth:'520px', display:'flex', flexDirection:'column' }}>
            {/* Header */}
            <div style={{ padding:'10px 16px 6px', borderBottom:'1px solid var(--border-strong)', background:'rgba(255,255,255,0.02)' }}>
              <div style={{ fontSize:'12px', fontWeight:600, color:'var(--text-primary)' }}>Cross-Asset Correlation Analysis</div>
            </div>

            {/* Controls */}
            <div style={{ padding:'10px 16px', background:'rgba(255,255,255,0.02)', borderBottom:'1px solid var(--border-strong)', display:'flex', alignItems:'center', gap:'20px', flexWrap:'wrap' }}>
              <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                <label style={{ fontSize:'11px', color:'var(--text-secondary)' }}>Lookback Period:</label>
                <select value={lookback} onChange={e => setLookback(e.target.value)} style={{ padding:'5px 10px', background:'var(--surface-input)', border:'1px solid var(--border-strong)', borderRadius:'4px', color:'var(--text-primary)', fontSize:'11px', cursor:'pointer' }}>
                  {['3 Months','6 Months','1 Year','2 Years'].map(o => <option key={o}>{o}</option>)}
                </select>
              </div>
              <div style={{ display:'flex', alignItems:'center', gap:'8px' }}>
                <label style={{ fontSize:'11px', color:'var(--text-secondary)' }}>Top Pairs:</label>
                <select value={topPairs} onChange={e => setTopPairs(e.target.value)} style={{ padding:'5px 10px', background:'var(--surface-input)', border:'1px solid var(--border-strong)', borderRadius:'4px', color:'var(--text-primary)', fontSize:'11px', cursor:'pointer' }}>
                  {['5','10','15','20'].map(o => <option key={o}>{o}</option>)}
                </select>
              </div>
              <button style={{ padding:'5px 14px', background:accentBlue, color:'#fff', border:'none', borderRadius:'4px', fontSize:'11px', fontWeight:700, cursor:'pointer', marginLeft:'auto' }}>Rank Correlations</button>
            </div>

            {/* Matrix scroll container */}
            <div style={{ flex:1, minHeight:'280px', overflowX:'auto', overflowY:'auto', padding:'12px 16px' }}>
              <table style={{ borderCollapse:'collapse', fontSize:'9px' }}>
                <thead>
                  <tr>
                    <td style={{ minWidth:'82px' }}></td>
                    {corrCols.map(c => (
                      <th key={c} style={{ padding:'2px 3px', writingMode:'vertical-rl', transform:'rotate(180deg)', whiteSpace:'nowrap', fontSize:'8px', color:'var(--text-muted)', maxHeight:'72px', verticalAlign:'bottom', textAlign:'left', fontWeight:400 }}>{c}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {corrRows.map((row, ri) => (
                    <tr key={row}>
                      <td style={{ padding:'2px 8px 2px 0', fontSize:'8px', color:'var(--text-muted)', whiteSpace:'nowrap', borderRight:'1px solid var(--border-strong)', textAlign:'right', fontWeight:400 }}>{row}</td>
                      {corrCols.slice(0, ri + 1).map(col => {
                        const v = getBetaCorr(row, col);
                        return (
                          <td key={col} style={{ padding:'2px', minWidth:'28px', height:'24px', background: betaCorrBg(v), textAlign:'center', fontSize:'8px', fontWeight:600, color:'rgba(255,255,255,0.9)', borderRadius:'2px' }}>
                            {v !== null ? v.toFixed(2) : ''}
                          </td>
                        );
                      })}
                      {corrCols.slice(ri + 1).map(col => (
                        <td key={col} style={{ minWidth:'28px', height:'24px' }}></td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Gradient legend */}
            <div style={{ padding:'10px 16px', borderTop:'1px solid var(--border-strong)', display:'flex', alignItems:'center', justifyContent:'center', gap:'10px' }}>
              <span style={{ fontSize:'8px', color:'var(--text-muted)' }}>1</span>
              <div style={{ width:'14px', height:'100px', borderRadius:'3px', background:'linear-gradient(to bottom, rgba(30,80,160,0.95) 0%, rgba(255,255,255,0.08) 50%, rgba(200,60,40,0.95) 100%)' }}></div>
              <div style={{ display:'flex', flexDirection:'column', gap:'24px', fontSize:'8px', color:'var(--text-muted)', minWidth:'20px' }}>
                <span>1</span>
                <span>0</span>
                <span>−1</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
window.BetaCandidates = BetaCandidates;
