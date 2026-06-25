// SummaryRisk.jsx — Summary > Risk subtab
// Combined Book Risk: KPI strip + Net Position chart + DV01 Ladder + collapsible inventory
const _ns_risk = window.AtlasNexusDesignSystem_988df3;

// ─── DATA ────────────────────────────────────────────────────────────────────
const SR_NET = [
  { inst: '250012.IB',   beta: 2720,  alpha: 0,     net: 2720,  dir: 'LONG'  },
  { inst: '260006.IB',   beta: 2720,  alpha: 0,     net: 2720,  dir: 'LONG'  },
  { inst: '240004.IB',   beta: 0,     alpha: -1410, net: -1410, dir: 'SHORT' },
  { inst: '260008.IB',   beta: 1460,  alpha: -110,  net: 1350,  dir: 'LONG'  },
  { inst: '250011.IB',   beta: 0,     alpha: 1300,  net: 1300,  dir: 'LONG'  },
  { inst: 'TL2609',      beta: 0,     alpha: 1140,  net: 1140,  dir: 'LONG'  },
  { inst: 'TL2612',      beta: 0,     alpha: -1140, net: -1140, dir: 'SHORT' },
  { inst: '260010.IB',   beta: 820,   alpha: 110,   net: 930,   dir: 'LONG'  },
  { inst: '2600001.IB',  beta: 490,   alpha: 0,     net: 490,   dir: 'LONG'  },
  { inst: 'EURCNY',      beta: 274,   alpha: 0,     net: 274,   dir: 'LONG'  },
  { inst: 'GBPCNY',      beta: 274,   alpha: 0,     net: 274,   dir: 'LONG'  },
  { inst: 'JPYCNY',      beta: 274,   alpha: 0,     net: 274,   dir: 'LONG'  },
  { inst: 'Silver',      beta: 274,   alpha: 0,     net: 274,   dir: 'LONG'  },
  { inst: 'USDCNY',      beta: 274,   alpha: 0,     net: 274,   dir: 'LONG'  },
  { inst: '2600002.IB',  beta: 370,   alpha: -110,  net: 260,   dir: 'LONG'  },
  { inst: '240013.IB',   beta: 0,     alpha: -220,  net: -220,  dir: 'SHORT' },
  { inst: '220003.IB',   beta: 0,     alpha: 110,   net: 110,   dir: 'LONG'  },
  { inst: '220017.IB',   beta: 0,     alpha: 110,   net: 110,   dir: 'LONG'  },
  { inst: '240203.IB',   beta: 0,     alpha: -110,  net: -110,  dir: 'SHORT' },
  { inst: '250016.IB',   beta: 0,     alpha: 110,   net: 110,   dir: 'LONG'  },
  { inst: '250022.IB',   beta: 0,     alpha: 110,   net: 110,   dir: 'LONG'  },
  { inst: '250208.IB',   beta: 0,     alpha: 110,   net: 110,   dir: 'LONG'  },
  { inst: '250218.IB',   beta: 0,     alpha: -110,  net: -110,  dir: 'SHORT' },
  { inst: '250355.IB',   beta: 0,     alpha: 110,   net: 110,   dir: 'LONG'  },
  { inst: '260005.IB',   beta: 0,     alpha: -110,  net: -110,  dir: 'SHORT' },
  { inst: '260203.IB',   beta: 0,     alpha: 110,   net: 110,   dir: 'LONG'  },
  { inst: 'FR007S2Y.IR', beta: 0,     alpha: -90,   net: -90,   dir: 'SHORT' },
  { inst: 'FR007S6M.IR', beta: 0,     alpha: 60,    net: 60,    dir: 'LONG'  },
  { inst:'FR007S10Y.IR', beta: 0,     alpha: -30,   net: -30,   dir: 'SHORT' },
  { inst: 'FR007S9M.IR', beta: 0,     alpha: 30,    net: 30,    dir: 'LONG'  },
  { inst: 'T2609',       beta: 0,     alpha: 30,    net: 30,    dir: 'LONG'  },
];

const SR_DV01 = [
  { tenor: '1Y',  bonds: 0.2584, swaps:  0.0177, futures: 0,      total: 0.2761 },
  { tenor: '2Y',  bonds: 0.5168, swaps: -0.0177, futures: 0,      total: 0.4991 },
  { tenor: '5Y',  bonds: 0.9171, swaps:  0,      futures: 0,      total: 0.9171 },
  { tenor: '10Y', bonds: 2.1546, swaps:  0,      futures: 0.0276, total: 2.1822 },
  { tenor: '20Y', bonds: 0.6370, swaps:  0,      futures: 0,      total: 0.6370 },
  { tenor: '30Y', bonds: 0.6290, swaps:  0,      futures: 3.1464, total: 3.7754 },
];

const SR_INV = [
  { book:'Beta',  name:'Silver',        inst:'Silver',       sector:'N/A',         cap: 274,  dv01: 0,      dir:'LONG' },
  { book:'Beta',  name:'USDCNY',        inst:'USDCNY',       sector:'N/A',         cap: 274,  dv01: 0,      dir:'LONG' },
  { book:'Beta',  name:'EURCNY',        inst:'EURCNY',       sector:'N/A',         cap: 274,  dv01: 0,      dir:'LONG' },
  { book:'Beta',  name:'JPYCNY',        inst:'JPYCNY',       sector:'N/A',         cap: 274,  dv01: 0,      dir:'LONG' },
  { book:'Beta',  name:'GBPCNY',        inst:'GBPCNY',       sector:'N/A',         cap: 274,  dv01: 0,      dir:'LONG' },
  { book:'Beta',  name:'CN1Y',          inst:'250012.IB',    sector:'1Y',          cap: 2720, dv01: 0.2584, dir:'LONG' },
  { book:'Beta',  name:'CN2Y',          inst:'260006.IB',    sector:'2Y',          cap: 2720, dv01: 0.5168, dir:'LONG' },
  { book:'Beta',  name:'CN5Y',          inst:'260008.IB',    sector:'5Y',          cap: 1460, dv01: 0.6570, dir:'LONG' },
  { book:'Beta',  name:'CN10Y',         inst:'260010.IB',    sector:'10Y',         cap: 820,  dv01: 0.6970, dir:'LONG' },
  { book:'Beta',  name:'CN20Y',         inst:'2600001.IB',   sector:'20Y',         cap: 490,  dv01: 0.6370, dir:'LONG' },
  { book:'Beta',  name:'CN30Y',         inst:'2600002.IB',   sector:'30Y',         cap: 370,  dv01: 0.6290, dir:'LONG' },
  { book:'Alpha', name:'TL',            inst:'TL',           sector:'TermBasis',   cap: 1140, dv01: 3.1464, dir:'BUY'  },
  { book:'Alpha', name:'Repo7d-6m1y',   inst:'FR007S6M.IR',  sector:'SwapSpread',  cap: 30,   dv01: 0.0030, dir:'BUY'  },
  { book:'Alpha', name:'CGB-10s30s',    inst:'260010.IB',    sector:'TenorSpread', cap: 110,  dv01: 0.1020, dir:'BUY'  },
  { book:'Alpha', name:'Repo7d-1y2y',   inst:'FR007S1Y.IR',  sector:'SwapSpread',  cap: 30,   dv01: 0.0059, dir:'BUY'  },
  { book:'Alpha', name:'T',             inst:'T2609',        sector:'FuturesSwap', cap: 30,   dv01: 0.0276, dir:'BUY'  },
  { book:'Alpha', name:'Repo7d-6m2y',   inst:'FR007S6M.IR',  sector:'SwapSpread',  cap: 30,   dv01: 0.0059, dir:'BUY'  },
  { book:'Alpha', name:'260005.IB',     inst:'260005.IB',    sector:'TBondCurve',  cap: 110,  dv01: 0.0981, dir:'BUY'  },
  { book:'Alpha', name:'250355.IB',     inst:'250355.IB',    sector:'CBondCurve',  cap: 110,  dv01: 0.0470, dir:'BUY'  },
  { book:'Alpha', name:'250016.IB',     inst:'250016.IB',    sector:'CBondCurve',  cap: 110,  dv01: 0.0930, dir:'BUY'  },
  { book:'Alpha', name:'250208.IB',     inst:'250208.IB',    sector:'CBondCurve',  cap: 110,  dv01: 0.0404, dir:'BUY'  },
  { book:'Alpha', name:'Repo7d-9m2y',   inst:'FR007S9M.IR',  sector:'SwapSpread',  cap: 30,   dv01: 0.0059, dir:'BUY'  },
  { book:'Alpha', name:'CDBCGB-5y',     inst:'260203.IB',    sector:'TenorSpread', cap: 110,  dv01: 0.0529, dir:'BUY'  },
  { book:'Alpha', name:'250011.IB',     inst:'250011.IB',    sector:'TBondCurve',  cap: 1300, dv01: 1.0692, dir:'BUY'  },
  { book:'Alpha', name:'220017.IB',     inst:'220017.IB',    sector:'TBondCurve',  cap: 110,  dv01: 0.0624, dir:'BUY'  },
  { book:'Alpha', name:'250022.IB',     inst:'250022.IB',    sector:'TBondCurve',  cap: 110,  dv01: 0.0953, dir:'BUY'  },
  { book:'Alpha', name:'220003.IB',     inst:'220003.IB',    sector:'TBondCurve',  cap: 110,  dv01: 0.0574, dir:'BUY'  },
];

// ─── CHART: Net Position horizontal diverging bars ────────────────────────────
function NetPosChart() {
  const top = [...SR_NET].sort((a, b) => Math.abs(b.net) - Math.abs(a.net)).slice(0, 15);

  const VBW = 560, ROW = 26, BAR = 14;
  const LW = 102, RW = 56;
  const H = top.length * ROW + 30;
  const barAreaW = VBW - LW - RW;
  // Skew zero 40% from left since portfolio is net-long
  const ZX = LW + barAreaW * 0.38;
  const MAX = 3000;
  const scalePos = barAreaW * 0.62 / MAX; // right of zero
  const scaleNeg = barAreaW * 0.38 / MAX; // left of zero

  function barColor(p) {
    if (p.beta !== 0 && p.alpha === 0) return '#3d8bd4';  // pure beta → blue
    if (p.beta === 0 && p.alpha > 0)   return '#e0a23c';  // pure alpha long → amber
    if (p.beta === 0 && p.alpha < 0)   return '#d56b6b';  // pure alpha short → red
    return p.net >= 0 ? '#41b078' : '#d56b6b';             // mixed
  }

  const ticks = [-2000, -1000, 0, 1000, 2000, 3000];

  return (
    <svg viewBox={`0 0 ${VBW} ${H}`} width="100%" style={{ display: 'block', fontFamily: '"IBM Plex Mono", monospace' }}>
      {/* Grid ticks */}
      {ticks.map(v => {
        const x = v >= 0 ? ZX + v * scalePos : ZX + v * scaleNeg;
        if (x < LW - 4 || x > VBW - RW + 4) return null;
        return (
          <g key={v}>
            <line x1={x} y1={0} x2={x} y2={H - 22}
              stroke={v === 0 ? 'rgba(255,255,255,0.18)' : 'rgba(255,255,255,0.05)'}
              strokeDasharray={v === 0 ? '3,4' : undefined} strokeWidth={1} />
            <text x={x} y={H - 8} textAnchor="middle" fill="#4a5d7c" fontSize={8.5}>
              {v === 0 ? '0' : `${v > 0 ? '+' : ''}${v / 1000}k`}
            </text>
          </g>
        );
      })}

      {/* Bars */}
      {top.map((p, i) => {
        const y = i * ROW + 4;
        const bY = y + (ROW - BAR) / 2;
        const isLong = p.net >= 0;
        const w = Math.abs(p.net) * (isLong ? scalePos : scaleNeg);
        const bX = isLong ? ZX : ZX - w;
        const c = barColor(p);
        const vX = isLong ? ZX + w + 4 : ZX - w - 4;

        return (
          <g key={p.inst}>
            {/* Label */}
            <text x={LW - 7} y={y + ROW / 2 + 4} textAnchor="end" fill="#a4b6d2" fontSize={11}>
              {p.inst}
            </text>
            {/* Bar */}
            <rect x={bX} y={bY} width={Math.max(w, 1)} height={BAR} fill={c} rx={1.5} opacity={0.88} />
            {/* Value */}
            <text x={vX} y={y + ROW / 2 + 4} textAnchor={isLong ? 'start' : 'end'}
              fill={isLong ? '#41b078' : '#d56b6b'} fontSize={9.5}>
              {p.net > 0 ? '+' : ''}{p.net.toFixed(0)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ─── CHART: DV01 Duration Ladder stacked bars ─────────────────────────────────
function DV01Chart() {
  const W = 400, H = 230;
  const PL = 42, PR = 16, PT = 22, PB = 34;
  const cW = W - PL - PR, cH = H - PT - PB;
  const slot = cW / SR_DV01.length, bW = slot * 0.64;
  const MAX_Y = 4.2;
  const ys = v => PT + cH - (v / MAX_Y) * cH;
  const C = { bonds: '#3d8bd4', swaps: '#45b6e6', futures: '#e0a23c' };

  return (
    <svg width={W} height={H} style={{ display: 'block', fontFamily: 'var(--font-mono)' }}>
      {/* Y grid */}
      {[0, 1, 2, 3, 4].map(v => (
        <g key={v}>
          <line x1={PL} y1={ys(v)} x2={W - PR} y2={ys(v)}
            stroke={v === 0 ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.06)'}
            strokeWidth={1} />
          {v > 0 && (
            <text x={PL - 5} y={ys(v) + 4} textAnchor="end" fill="#4a5d7c" fontSize={9}>{v}</text>
          )}
        </g>
      ))}

      {/* Bars */}
      {SR_DV01.map((r, i) => {
        const bx = PL + i * slot + (slot - bW) / 2;
        const baseY = ys(0);
        let stackY = baseY;
        const segs = [];

        if (r.bonds > 0)   { const h = r.bonds   / MAX_Y * cH; stackY -= h; segs.push({ y: stackY, h, fill: C.bonds   }); }
        if (r.swaps > 0)   { const h = r.swaps   / MAX_Y * cH; stackY -= h; segs.push({ y: stackY, h, fill: C.swaps   }); }
        if (r.futures > 0) { const h = r.futures / MAX_Y * cH; stackY -= h; segs.push({ y: stackY, h, fill: C.futures }); }

        const topY = segs.length ? segs[segs.length - 1].y : baseY;

        return (
          <g key={r.tenor}>
            {segs.map((s, si) => (
              <rect key={si} x={bx} y={s.y} width={bW} height={s.h} fill={s.fill}
                rx={si === segs.length - 1 ? 2 : 0} opacity={0.9} />
            ))}
            {/* Negative swap notch (2Y: swaps = -0.0177 bites into top of bonds) */}
            {r.swaps < 0 && (
              <rect x={bx} y={baseY - r.bonds / MAX_Y * cH}
                width={bW} height={Math.abs(r.swaps) / MAX_Y * cH}
                fill="#0a1428" opacity={0.7} />
            )}
            {/* Total label */}
            <text x={bx + bW / 2} y={topY - 5} textAnchor="middle" fill="#a4b6d2" fontSize={9}>
              {r.total.toFixed(2)}
            </text>
            {/* Tenor label */}
            <text x={bx + bW / 2} y={baseY + 15} textAnchor="middle" fill="#c0cfe8" fontSize={10.5}>
              {r.tenor}
            </text>
          </g>
        );
      })}

      {/* Legend */}
      {[{ c: C.bonds, l: 'Bonds' }, { c: C.swaps, l: 'Swaps' }, { c: C.futures, l: 'Futures' }].map((item, i) => (
        <g key={item.l} transform={`translate(${PL + i * 108}, ${H - 2})`}>
          <rect y={-8} width={7} height={7} fill={item.c} rx={1} />
          <text x={11} fill="#6f83a3" fontSize={9} fontFamily="var(--font-sans)">{item.l}</text>
        </g>
      ))}
    </svg>
  );
}

// ─── CHART: Factor Risk Attribution ──────────────────────────────────────────
const SR_FACTOR = [
  { factor: 'CMDL.AG',      netExp: 0.0256,  rc:  75.5, tgt: 16.7, delta:  58.8 },
  { factor: 'CMDL.AU',      netExp: 0.0256,  rc:  26.1, tgt: 16.7, delta:   9.4 },
  { factor: 'IRDL.CN',      netExp: 1.1767,  rc:   0.1, tgt: 16.7, delta: -16.6 },
  { factor: 'IRSL.CN',      netExp: 0.0551,  rc:   0.1, tgt: 16.7, delta: -16.6 },
  { factor: 'IRCV.CN',      netExp: 0.0426,  rc:   0.0, tgt: 16.7, delta: -16.7 },
  { factor: 'FXDL.USDCNY', netExp: 0.0256,  rc:  -1.8, tgt: 16.7, delta: -18.5 },
];

function FactorRiskChart() {
  // viewBox W matches the ~400px rendered column so fonts render 1:1 (same as DV01 chart)
  const W = 400, H = 188;
  const PL = 86, PR = 104, PT = 18, PB = 26;
  const cW = W - PL - PR, cH = H - PT - PB;
  const MAX_X = 1.4;
  const ROW = cH / SR_FACTOR.length;
  const BAR = ROW * 0.44;
  // sqrt scale so IRDL.CN (1.18) doesn't dwarf the small factors
  const xs = v => PL + (Math.sqrt(v) / Math.sqrt(MAX_X)) * cW;

  const barColor = (delta) => {
    if (delta > 10) return '#e0a23c';
    if (delta > 0)  return '#c8a060';
    if (delta > -10) return '#6b8cb8';
    return '#d56b6b';
  };

  // Tick positions at actual values, rendered at their sqrt positions
  const ticks = [0, 0.05, 0.1, 0.25, 0.5, 1.0, 1.4];

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: 'block', fontFamily: 'var(--font-mono)' }}>
      {/* Grid */}
      {ticks.map(v => (
        <g key={v}>
          <line x1={xs(v)} y1={PT} x2={xs(v)} y2={H - PB}
            stroke={v === 0 ? 'rgba(255,255,255,0.15)' : 'rgba(255,255,255,0.05)'}
            strokeWidth={1} />
          <text x={xs(v)} y={H - PB + 14} textAnchor="middle" fill="#4a5d7c" fontSize={9}>
            {v}
          </text>
        </g>
      ))}
      {/* sqrt scale note */}
      <text x={W - PR + 8} y={H - PB + 14} fill="#4a5d7c" fontSize={8} fontStyle="italic">
        √ scale
      </text>

      {/* Bars */}
      {SR_FACTOR.map((r, i) => {
        const y = PT + i * ROW;
        const bY = y + (ROW - BAR) / 2;
        const bW = Math.max((r.netExp / MAX_X) * cW, 2);
        const col = barColor(r.delta);

        return (
          <g key={r.factor}>
            {/* Factor label */}
            <text x={PL - 8} y={y + ROW / 2 + 4} textAnchor="end"
              fill="#a4b6d2" fontSize={10.5}>{r.factor}</text>

            {/* Bar */}
            <rect x={xs(0)} y={bY} width={bW} height={BAR} fill={col} rx={2} opacity={0.85} />

            {/* Net Exp. value */}
            <text x={xs(0) + bW + 6} y={y + ROW / 2 + 4} textAnchor="start"
              fill={col} fontSize={9}>{r.netExp.toFixed(4)}</text>

            {/* RC % and Δ RC % on right */}
            <text x={W - PR + 8} y={y + ROW / 2 + 4} textAnchor="start"
              fill="#4a5d7c" fontSize={9}>
              RC {r.rc.toFixed(1)}
            </text>
            <text x={W - PR + 56} y={y + ROW / 2 + 4} textAnchor="start"
              fill={col} fontSize={9} fontWeight="500">
              {r.delta > 0 ? '+' : ''}{r.delta.toFixed(1)}
            </text>
          </g>
        );
      })}

      {/* Right column headers */}
      <text x={W - PR + 8} y={PT - 4} textAnchor="start" fill="#4a5d7c" fontSize={9}
        letterSpacing="0.05em">RC %</text>
      <text x={W - PR + 56} y={PT - 4} textAnchor="start" fill="#4a5d7c" fontSize={9}
        letterSpacing="0.05em">Δ RC %</text>
    </svg>
  );
}

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────
function SummaryRisk() {
  const { useState } = React;
  const { Panel, KPICard, DataTable, Badge, SignedValue, Button } = _ns_risk;
  const [showInv, setShowInv] = useState(false);

  // Derived metrics
  const totalDv01  = SR_DV01.reduce((s, r) => s + r.total, 0);
  const totalLong  = SR_NET.filter(p => p.net > 0).reduce((s, p) => s + p.net, 0);
  const totalShort = SR_NET.filter(p => p.net < 0).reduce((s, p) => s + Math.abs(p.net), 0);
  const netExp     = totalLong - totalShort;

  // Table columns for full inventory
  const invCols = [
    { key: 'book',   label: 'Book',         align: 'left',  render: v => <Badge tone={v === 'Beta' ? 'cyan' : 'amber'}>{v}</Badge> },
    { key: 'name',   label: 'Name',         align: 'left'  },
    { key: 'inst',   label: 'Instrument',   align: 'left'  },
    { key: 'sector', label: 'Sector',       align: 'left'  },
    { key: 'cap',    label: 'Capital (MM)', render: v => <SignedValue value={v} digits={2} /> },
    { key: 'dv01',   label: 'DV01 (MM/bp)', render: v => v ? v.toFixed(4) : '—' },
    { key: 'dir',    label: 'Dir',          render: v => <Badge tone={v === 'LONG' || v === 'BUY' ? 'buy' : 'sell'}>{v}</Badge> },
  ];

  // Collapsed summary helpers
  const Row = ({ label, value, dim }) => (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '3px 0',
      borderBottom: '1px solid var(--border-subtle)' }}>
      <span style={{ font: 'var(--type-data)', color: 'var(--text-secondary)' }}>{label}</span>
      <span style={{ font: 'var(--type-data)', color: dim ? 'var(--text-muted)' : 'var(--text-primary)' }}>{value}</span>
    </div>
  );

  const betaRows = SR_INV.filter(r => r.book === 'Beta');
  const alphaRows = SR_INV.filter(r => r.book === 'Alpha');
  const sectorTotals = Object.entries(
    SR_INV.reduce((acc, r) => { acc[r.sector] = (acc[r.sector] || 0) + r.cap; return acc; }, {})
  ).sort((a, b) => b[1] - a[1]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

      {/* ── Header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div style={{ font: 'var(--type-h1)', color: 'var(--text-primary)' }}>Combined Book Risk</div>
        <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
          <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)' }}>
            11 beta · 16 alpha · updated 21:20:42
          </span>
          <Button variant="outline" size="sm" accent="cyan">Refresh</Button>
        </div>
      </div>

      {/* ── KPI strip ── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px' }}>
        <KPICard label="Total Long"
          value={`+${(totalLong / 1000).toFixed(1)}k`}
          accent="green" sub="MM notional, net long legs" />
        <KPICard label="Total Short"
          value={`-${(totalShort / 1000).toFixed(1)}k`}
          accent="amber" sub="MM notional, net short legs" />
        <KPICard label="Net Exposure"
          value={`${netExp > 0 ? '+' : ''}${(netExp / 1000).toFixed(1)}k`}
          accent="cyan" sub="Beta + Alpha combined" />
        <KPICard label="Total DV01"
          value={`${totalDv01.toFixed(2)}`}
          accent="blue" sub="MM/bp aggregate sensitivity" />
      </div>

      {/* ── Charts ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 440px', gap: '16px', alignItems: 'start' }}>

        {/* Net Position — left, full height */}
        <Panel eyebrow="Net Position by Instrument" accent="cyan" style={{ height: '100%' }}>
          <div style={{ display: 'flex', gap: '18px', marginBottom: '10px', flexWrap: 'wrap' }}>
            {[
              ['#3d8bd4', 'Beta only'],
              ['#e0a23c', 'Alpha long'],
              ['#d56b6b', 'Alpha short'],
              ['#41b078', 'Mixed long'],
            ].map(([c, l]) => (
              <div key={l} style={{ display: 'flex', alignItems: 'center', gap: '5px',
                font: 'var(--type-meta)', color: 'var(--text-muted)' }}>
                <div style={{ width: 8, height: 8, borderRadius: 1, background: c, flexShrink: 0 }} />
                {l}
              </div>
            ))}
          </div>
          <NetPosChart />
        </Panel>

        {/* Right column: DV01 + Factor Risk stacked */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

        {/* DV01 Ladder */}
        <Panel eyebrow="DV01 Duration Ladder (MM/bp)" accent="blue">
          <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginBottom: '12px', lineHeight: '1.6' }}>
            Bonds = Treasury/Policybank/CDB · Swaps = IRS/Repo/ICP · Futures = Bond futures, term basis
          </div>
          <div style={{ overflowX: 'auto' }}>
            <DV01Chart />
          </div>
          {/* Tenor totals strip */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: '4px',
            marginTop: '12px', borderTop: '1px solid var(--border-subtle)', paddingTop: '10px' }}>
            {SR_DV01.map(r => (
              <div key={r.tenor} style={{ textAlign: 'center' }}>
                <div style={{ font: 'var(--type-th)', letterSpacing: 'var(--ls-label)',
                  textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '2px' }}>
                  {r.tenor}
                </div>
                <div style={{ font: 'var(--type-data)',
                  color: r.total >= 2 ? '#e0a23c' : 'var(--text-primary)' }}>
                  {r.total.toFixed(4)}
                </div>
              </div>
            ))}
          </div>
        </Panel>

          {/* Factor Risk Attribution */}
          <Panel eyebrow="Factor Risk Attribution" accent="amber">
            <div style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', marginBottom: '8px', fontStyle: 'italic' }}>
              Beta book · Net Exp. · colored by Δ RC %
            </div>
            <FactorRiskChart />
          </Panel>
        </div>
      </div>

      {/* ── Position Inventory (collapsible) ── */}
      <Panel
        eyebrow="Position Inventory (Beta + Alpha)"
        accent="cyan"
        actions={
          <Button variant="ghost" size="sm" onClick={() => setShowInv(s => !s)}>
            {showInv ? '▲ Collapse' : '▼ Expand table'}
          </Button>
        }
      >
        {showInv ? (
          <DataTable columns={invCols} rows={SR_INV} compact />
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '28px' }}>
            {/* Beta book */}
            <div>
              <div style={{ font: 'var(--type-label)', letterSpacing: 'var(--ls-label)',
                textTransform: 'uppercase', color: '#3d8bd4', marginBottom: '8px' }}>
                Beta Book — {betaRows.length} positions
              </div>
              {betaRows.map(r => (
                <Row key={r.name} label={r.name} value={`+${r.cap.toLocaleString()}`} />
              ))}
            </div>

            {/* Alpha book */}
            <div>
              <div style={{ font: 'var(--type-label)', letterSpacing: 'var(--ls-label)',
                textTransform: 'uppercase', color: '#e0a23c', marginBottom: '8px' }}>
                Alpha Book — {alphaRows.length} positions
              </div>
              {alphaRows.map(r => (
                <Row key={`${r.name}-${r.inst}`}
                  label={r.name}
                  value={`${r.cap >= 0 ? '+' : ''}${r.cap.toLocaleString()}`}
                  dim={Math.abs(r.cap) < 50} />
              ))}
            </div>

            {/* By sector */}
            <div>
              <div style={{ font: 'var(--type-label)', letterSpacing: 'var(--ls-label)',
                textTransform: 'uppercase', color: 'var(--text-muted)', marginBottom: '8px' }}>
                Capital by Sector
              </div>
              {sectorTotals.map(([sec, tot]) => (
                <Row key={sec} label={sec} value={`+${tot.toLocaleString()}`} />
              ))}
            </div>
          </div>
        )}
      </Panel>

    </div>
  );
}

window.SummaryRisk = SummaryRisk;
