// Beta Book > Futures — Strategy Config sidebar + candlestick chart
const _ns_bfut = window.AtlasNexusDesignSystem_988df3;

const SYMBOLS = ['TL.CFE','T.CFE','TF.CFE','TS.CFE','IF.CFE','IC.CFE'];
const IN_SAMPLES = ['6M','1 Yr','2 Yr','3 Yr'];
const STRATEGIES_LIST = [
  { key:'MA',       label:'MA',        checked:true  },
  { key:'Bollinger',label:'Bollinger', checked:true  },
  { key:'Momentum', label:'Momentum',  checked:false },
  { key:'SAR',      label:'SAR',       checked:true  },
  { key:'DeMark',   label:'DeMark',    checked:false },
  { key:'VWAP',     label:'VWAP',      checked:false },
  { key:'ATR',      label:'ATR',       checked:false },
  { key:'MktRegime',label:'Mkt Regime',checked:true  },
];

// Mock candlestick data
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

function BetaFutures() {
  const { useState } = React;
  const [source, setSource] = useState('Local');
  const [mode, setMode] = useState('Daily');
  const [symbol, setSymbol] = useState('TL.CFE');
  const [startDate, setStartDate] = useState('2026-05-27');
  const [endDate, setEndDate] = useState('2026-06-26');
  const [oosDate, setOosDate] = useState('2026-06-26');
  const [inSample, setInSample] = useState('1 Yr');
  const [strategies, setStrategies] = useState(() => Object.fromEntries(STRATEGIES_LIST.map(s=>[s.key,s.checked])));
  const [trending, setTrending] = useState('SAR');
  const [meanRev, setMeanRev] = useState('Boll');
  const [maShort, setMaShort] = useState('5');
  const [maLong, setMaLong] = useState('20');
  const [expandedParams, setExpandedParams] = useState({MA:true});

  const accentBlue = 'var(--accent-blue)';
  const accentCyan = 'var(--accent-cyan)';

  const toggleStrategy = (k) => setStrategies(s=>({...s,[k]:!s[k]}));
  const toggleParam = (k) => setExpandedParams(e=>({...e,[k]:!e[k]}));

  // Chart
  const W=700, H=320;
  const allPrices = CANDLES.flatMap(c=>[c.h,c.l]);
  const yMin = Math.min(...allPrices)-0.05, yMax = Math.max(...allPrices)+0.05;
  const rng = yMax-yMin;
  const cw = (W-60)/CANDLES.length;
  function cy(v){ return H-30-((v-yMin)/rng)*(H-50); }
  function cx(i){ return 40+i*cw+cw/2; }

  const yTicks = [];
  for(let v=Math.ceil(yMin/0.2)*0.2; v<=yMax; v=Math.round((v+0.2)*100)/100) yTicks.push(v);

  // Date labels - show every 3rd
  const xLabels = CANDLES.filter((_,i)=>i%3===0);

  const Radio = ({val, cur, set, label}) => (
    <label style={{ display:'flex', alignItems:'center', gap:'4px', cursor:'pointer', font:'var(--type-label)', fontSize:'10px', color: cur===val?'var(--text-primary)':'var(--text-muted)' }}>
      <div onClick={()=>set(val)} style={{ width:'10px', height:'10px', borderRadius:'50%', border:'2px solid '+(cur===val?accentBlue:'var(--border-strong)'), background:cur===val?accentBlue:'transparent', flexShrink:0, cursor:'pointer' }}></div>
      <span onClick={()=>set(val)}>{label}</span>
    </label>
  );

  const Checkbox = ({checked, onChange, label}) => (
    <label style={{ display:'flex', alignItems:'center', gap:'5px', cursor:'pointer', font:'var(--type-label)', fontSize:'10px', color: checked?'var(--text-primary)':'var(--text-muted)' }}>
      <div onClick={onChange} style={{ width:'11px', height:'11px', borderRadius:'2px', border:'2px solid '+(checked?accentBlue:'var(--border-strong)'), background:checked?accentBlue:'transparent', flexShrink:0, cursor:'pointer', display:'flex', alignItems:'center', justifyContent:'center' }}>
        {checked && <svg width="7" height="5" viewBox="0 0 8 6" fill="none"><path d="M1 3L3 5L7 1" stroke="#fff" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/></svg>}
      </div>
      <span onClick={onChange}>{label}</span>
    </label>
  );

  const Stepper = ({value, onChange}) => (
    <div style={{ display:'flex', alignItems:'center', border:'1px solid var(--border-default)', borderRadius:'4px', overflow:'hidden', background:'var(--surface-input)' }}>
      <button onClick={()=>onChange(String(Math.max(1,(parseInt(value)||0)-1)))} style={{ width:'24px', height:'28px', border:'none', background:'transparent', color:'var(--text-muted)', cursor:'pointer', fontSize:'14px', borderRight:'1px solid var(--border-default)' }}>−</button>
      <input value={value} onChange={e=>onChange(e.target.value)} style={{ width:'40px', border:'none', background:'transparent', font:'var(--type-data)', fontSize:'11px', color:'var(--text-primary)', textAlign:'center', padding:'0' }}/>
      <button onClick={()=>onChange(String((parseInt(value)||0)+1))} style={{ width:'24px', height:'28px', border:'none', background:'transparent', color:'var(--text-muted)', cursor:'pointer', fontSize:'14px', borderLeft:'1px solid var(--border-default)' }}>+</button>
    </div>
  );

  return (
    <div style={{ display:'flex', gap:'0', alignItems:'start' }}>

      {/* LEFT SIDEBAR */}
      <div style={{ width:'220px', flexShrink:0, marginRight:'14px', display:'flex', flexDirection:'column', gap:'0' }}>
        <div style={{ background:'var(--surface-panel)', border:'1px solid var(--border-strong)', borderRadius:'8px', overflow:'hidden' }}>
          {/* Title */}
          <div style={{ padding:'10px 14px', borderBottom:'1px solid var(--border-strong)' }}>
            <span style={{ font:'var(--type-label)', color:'var(--text-primary)', fontSize:'11px', fontWeight:600 }}>Strategy Config</span>
          </div>

          <div style={{ padding:'12px 14px', borderBottom:'1px solid var(--border-default)' }}>
            <div style={{ font:'var(--type-label)', color:accentBlue, fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>Data Settings</div>
            <div style={{ display:'flex', gap:'10px', marginBottom:'6px' }}>
              <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'10px' }}>Source</span>
              <Radio val="Local" cur={source} set={setSource} label="Local"/>
              <Radio val="Wind"  cur={source} set={setSource} label="Wind"/>
            </div>
            <div style={{ display:'flex', gap:'10px', marginBottom:'10px' }}>
              <span style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'10px' }}>Mode</span>
              <Radio val="Daily"   cur={mode} set={setMode} label="Daily"/>
              <Radio val="Intraday" cur={mode} set={setMode} label="Intraday"/>
            </div>
            <div style={{ marginBottom:'6px' }}>
              <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', marginBottom:'4px' }}>Local Symbol</div>
              <div style={{ position:'relative' }}>
                <select value={symbol} onChange={e=>setSymbol(e.target.value)} style={{ appearance:'none', width:'100%', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'6px 24px 6px 8px', font:'var(--type-data)', fontSize:'11px', color:'var(--text-primary)', cursor:'pointer' }}>
                  {SYMBOLS.map(s=><option key={s}>{s}</option>)}
                </select>
                <svg width="10" height="10" viewBox="0 0 12 12" fill="none" style={{ position:'absolute', right:'7px', top:'50%', transform:'translateY(-50%)', pointerEvents:'none' }}><path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
              </div>
            </div>
            <div style={{ marginBottom:'8px' }}>
              <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', marginBottom:'4px' }}>Date Range</div>
              <div style={{ display:'flex', alignItems:'center', gap:'4px' }}>
                <input type="date" value={startDate} onChange={e=>setStartDate(e.target.value)} style={{ flex:1, background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 6px', font:'var(--type-data)', fontSize:'9px', color:'var(--text-primary)', colorScheme:'dark' }}/>
                <span style={{ color:'var(--text-muted)', fontSize:'10px' }}>→</span>
                <input type="date" value={endDate} onChange={e=>setEndDate(e.target.value)} style={{ flex:1, background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 6px', font:'var(--type-data)', fontSize:'9px', color:'var(--text-primary)', colorScheme:'dark' }}/>
              </div>
            </div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'6px' }}>
              <div>
                <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', marginBottom:'3px' }}>OOS Split</div>
                <input type="date" value={oosDate} onChange={e=>setOosDate(e.target.value)} style={{ width:'100%', boxSizing:'border-box', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 6px', font:'var(--type-data)', fontSize:'9px', color:'var(--text-primary)', colorScheme:'dark' }}/>
              </div>
              <div>
                <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', marginBottom:'3px' }}>In-sample</div>
                <div style={{ position:'relative' }}>
                  <select value={inSample} onChange={e=>setInSample(e.target.value)} style={{ appearance:'none', width:'100%', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 20px 5px 7px', font:'var(--type-data)', fontSize:'10px', color:'var(--text-primary)', cursor:'pointer' }}>
                    {IN_SAMPLES.map(s=><option key={s}>{s}</option>)}
                  </select>
                  <svg width="8" height="8" viewBox="0 0 12 12" fill="none" style={{ position:'absolute', right:'5px', top:'50%', transform:'translateY(-50%)', pointerEvents:'none' }}><path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
                </div>
              </div>
            </div>
          </div>

          {/* Strategies */}
          <div style={{ padding:'10px 14px', borderBottom:'1px solid var(--border-default)' }}>
            <div style={{ font:'var(--type-label)', color:accentBlue, fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>Strategies</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'5px 10px' }}>
              {STRATEGIES_LIST.map(s=>(
                <Checkbox key={s.key} checked={!!strategies[s.key]} onChange={()=>toggleStrategy(s.key)} label={s.label}/>
              ))}
            </div>
          </div>

          {/* Regime Logic */}
          <div style={{ padding:'10px 14px', borderBottom:'1px solid var(--border-default)' }}>
            <div style={{ font:'var(--type-label)', color:accentBlue, fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>Regime Logic</div>
            <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'8px' }}>
              <div>
                <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', marginBottom:'3px' }}>Trending</div>
                <div style={{ position:'relative' }}>
                  <select value={trending} onChange={e=>setTrending(e.target.value)} style={{ appearance:'none', width:'100%', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 20px 5px 7px', font:'var(--type-data)', fontSize:'10px', color:'var(--text-primary)', cursor:'pointer' }}>
                    {['SAR','MA','ATR'].map(s=><option key={s}>{s}</option>)}
                  </select>
                  <svg width="8" height="8" viewBox="0 0 12 12" fill="none" style={{ position:'absolute', right:'5px', top:'50%', transform:'translateY(-50%)', pointerEvents:'none' }}><path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
                </div>
              </div>
              <div>
                <div style={{ font:'var(--type-label)', color:'var(--text-muted)', fontSize:'9px', marginBottom:'3px' }}>Mean-Rev</div>
                <div style={{ position:'relative' }}>
                  <select value={meanRev} onChange={e=>setMeanRev(e.target.value)} style={{ appearance:'none', width:'100%', background:'var(--surface-input)', border:'1px solid var(--border-default)', borderRadius:'4px', padding:'5px 20px 5px 7px', font:'var(--type-data)', fontSize:'10px', color:'var(--text-primary)', cursor:'pointer' }}>
                    {['Boll','MA','VWAP'].map(s=><option key={s}>{s}</option>)}
                  </select>
                  <svg width="8" height="8" viewBox="0 0 12 12" fill="none" style={{ position:'absolute', right:'5px', top:'50%', transform:'translateY(-50%)', pointerEvents:'none' }}><path d="M3 4.5l3 3 3-3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
                </div>
              </div>
            </div>
          </div>

          {/* Parameters */}
          <div style={{ padding:'10px 14px', borderBottom:'1px solid var(--border-default)' }}>
            <div style={{ font:'var(--type-label)', color:accentBlue, fontSize:'9px', textTransform:'uppercase', letterSpacing:'0.08em', marginBottom:'8px' }}>Parameters</div>
            {/* MA expanded */}
            <div style={{ marginBottom:'6px' }}>
              <div onClick={()=>toggleParam('MA')} style={{ display:'flex', alignItems:'center', gap:'4px', cursor:'pointer', marginBottom: expandedParams.MA?'8px':'0' }}>
                <span style={{ color:'var(--text-muted)', fontSize:'10px' }}>{expandedParams.MA?'▼':'►'}</span>
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
            {['BOLLINGER','VWAP','MOMENTUM','ATR','SAR'].map(k=>(
              <div key={k} onClick={()=>toggleParam(k)} style={{ display:'flex', alignItems:'center', gap:'4px', cursor:'pointer', padding:'2px 0' }}>
                <span style={{ color:'var(--text-muted)', fontSize:'10px' }}>{expandedParams[k]?'▼':'►'}</span>
                <span style={{ font:'var(--type-label)', fontSize:'10px', color:'var(--text-secondary)', fontWeight:600 }}>{k}</span>
              </div>
            ))}
          </div>

          {/* Run button */}
          <div style={{ padding:'12px 14px' }}>
            <button style={{ width:'100%', padding:'9px', font:'var(--type-label)', fontSize:'11px', fontWeight:700, background: accentBlue, color:'#fff', border:'none', borderRadius:'5px', cursor:'pointer', letterSpacing:'0.04em', transition:'filter 0.15s' }}
              onMouseEnter={e=>e.target.style.filter='brightness(1.15)'}
              onMouseLeave={e=>e.target.style.filter='brightness(1)'}
            >Run Backtest</button>
          </div>
        </div>
      </div>

      {/* MAIN CHART */}
      <div style={{ flex:1, minWidth:0, background:'var(--surface-panel)', border:'1px solid var(--border-strong)', borderRadius:'8px', padding:'14px 16px' }}>
        <div style={{ font:'var(--type-h3)', color:'var(--text-primary)', fontSize:'14px', marginBottom:'14px' }}>{symbol} — Price</div>
        <svg viewBox={`0 0 ${W} ${H}`} style={{ width:'100%', height:'auto' }} preserveAspectRatio="xMidYMid meet">
          {/* Grid lines */}
          {yTicks.map((v,i)=>(
            <g key={i}>
              <line x1="40" y1={cy(v)} x2={W-5} y2={cy(v)} stroke="rgba(100,140,200,0.12)" strokeWidth="0.8"/>
              <text x="35" y={cy(v)+4} textAnchor="end" fontSize="9" fill="rgba(150,180,220,0.7)">{v.toFixed(1)}</text>
            </g>
          ))}
          {/* X labels */}
          {xLabels.map((c,i)=>{
            const idx = CANDLES.indexOf(c);
            return <text key={i} x={cx(idx)} y={H-8} textAnchor="middle" fontSize="9" fill="rgba(150,180,220,0.6)">{c.d}</text>;
          })}
          {/* Candlesticks */}
          {CANDLES.map((c,i)=>{
            const bull = c.c >= c.o;
            const color = bull ? '#4ade80' : '#f87171';
            const bodyTop = cy(Math.max(c.o,c.c));
            const bodyBot = cy(Math.min(c.o,c.c));
            const bodyH = Math.max(bodyBot-bodyTop, 2);
            const x = cx(i);
            const bw = cw*0.55;
            return (
              <g key={i}>
                {/* Wick */}
                <line x1={x} y1={cy(c.h)} x2={x} y2={cy(c.l)} stroke={color} strokeWidth="1.2" opacity="0.85"/>
                {/* Body */}
                <rect x={x-bw/2} y={bodyTop} width={bw} height={bodyH} fill={color} opacity="0.85" rx="1"/>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
window.BetaFutures = BetaFutures;
