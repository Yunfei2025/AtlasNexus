// Market > Data — market data snapshot screen.
// Matches atlas_market_data_tab.py layout exactly:
//   Left col:  Money Market Rates / Reference Bonds / Bond Futures & CTD
//   Right col: On-the-run Bonds   / IRS Forward Rates (6 cols, shifted headers)
const _ns_md = window.AtlasNexusDesignSystem_988df3;

function MarketData() {
  const { Panel, DataTable, BarCell, Button, Input } = _ns_md;
  const { useState } = React;

  // ── shift inputs state (mirrors dcc.Input ids) ────────────────────────────
  const [r7dShift, setR7dShift] = useState(0);
  const [s3mShift, setS3mShift] = useState(0);

  // ── Money Market Rates ────────────────────────────────────────────────────
  const mmCols = [
    { key: 'ref',   label: 'Reference',   align: 'left' },
    { key: 'close', label: 'Close (%)' },
    { key: 'quote', label: 'Quote (%)' },
    { key: 'chg',   label: 'Chg (bp)',     render: (v) => <BarCell value={v} max={2}  /> },
    { key: 'cr',    label: 'CR (3m, bp)',  render: (v) => <BarCell value={v} max={8}  /> },
  ];
  const mmRows = [
    { ref: 'FR001.IR',     close: '1.46',   quote: '1.46',   chg: 0,     cr: '—'    },
    { ref: 'FR007.IR',     close: '1.48',   quote: '1.48',   chg: 0,     cr: '—'    },
    { ref: 'SHIBOR3M.IR',  close: '1.43',   quote: '1.43',   chg: 0,     cr: '—'    },
    { ref: 'FR007S1Y.IR',  close: '1.445',  quote: '1.4587', chg: 1.37,  cr: 1.1    },
    { ref: 'FR007S5Y.IR',  close: '1.5225', quote: '1.5463', chg: 2.38,  cr: -4.68  },
    { ref: 'SHI3MS1Y.IR',  close: '1.46',   quote: '1.48',   chg: 2,     cr: -0.88  },
    { ref: 'SHI3MS5Y.IR',  close: '1.5775', quote: '1.6013', chg: 2.38,  cr: -7.71  },
  ];

  // ── On-the-run Bonds ──────────────────────────────────────────────────────
  const otrCols = [
    { key: 'tenor',  label: 'Tenor',  align: 'left' },
    { key: 'cgb',    label: 'CGB'   },
    { key: 'cgbcr',  label: 'CR,3M', render: (v) => <BarCell value={v} max={11} /> },
    { key: 'cdb',    label: 'CDB'   },
    { key: 'cdbcr',  label: 'CR,3M', render: (v) => <BarCell value={v} max={11} /> },
  ];
  const otrRows = [
    { tenor: '1Y',  cgb: '250012.IB',  cgbcr: -9.34, cdb: '250202.IB', cdbcr: -2.56 },
    { tenor: '2Y',  cgb: '260006.IB',  cgbcr: -4.03, cdb: '260202.IB', cdbcr: 1.44  },
    { tenor: '5Y',  cgb: '260008.IB',  cgbcr: 10.16, cdb: '260203.IB', cdbcr: 9.16  },
    { tenor: '10Y', cgb: '260010.IB',  cgbcr: 10.77, cdb: '260205.IB', cdbcr: 10.73 },
    { tenor: '20Y', cgb: '2600001.IB', cgbcr: '—',   cdb: '210220.IB', cdbcr: '—'   },
    { tenor: '30Y', cgb: '2600002.IB', cgbcr: '—',   cdb: '210221.IB', cdbcr: '—'   },
  ];

  // ── Reference Bonds (full 11-tenor list from _load_reference_bonds) ───────
  const refCols = [
    { key: 'tenor',  label: 'Tenor',  align: 'left' },
    { key: 'cgb',    label: 'CGB'   },
    { key: 'cgbcr',  label: 'CR,3M', render: (v) => <BarCell value={v} max={40} /> },
    { key: 'cdb',    label: 'CDB'   },
    { key: 'cdbcr',  label: 'CR,3M', render: (v) => <BarCell value={v} max={40} /> },
  ];
  const refRows = [
    { tenor: '0.3Y', cgb: '210011.IB',  cgbcr: -38.91, cdb: '250211.IB', cdbcr: -35.75 },
    { tenor: '0.5Y', cgb: '269931.IB',  cgbcr: '—',    cdb: '240202.IB', cdbcr: -3.52  },
    { tenor: '0.7Y', cgb: '260009.IB',  cgbcr: '—',    cdb: '260201.IB', cdbcr: -2.76  },
    { tenor: '1Y',   cgb: '250012.IB',  cgbcr: -9.34,  cdb: '250202.IB', cdbcr: -2.56  },
    { tenor: '1.5Y', cgb: '250024.IB',  cgbcr: -5.6,   cdb: '230203.IB', cdbcr: 0.89   },
    { tenor: '2Y',   cgb: '230022.IB',  cgbcr: -2.2,   cdb: '230208.IB', cdbcr: 2.05   },
    { tenor: '3Y',   cgb: '240001.IB',  cgbcr: -0.29,  cdb: '240203.IB', cdbcr: 4.03   },
    { tenor: '5Y',   cgb: '240013.IB',  cgbcr: 10.64,  cdb: '250218.IB', cdbcr: 9.05   },
    { tenor: '10Y',  cgb: '260005.IB',  cgbcr: 11.43,  cdb: '250220.IB', cdbcr: 11.83  },
    { tenor: '20Y',  cgb: '210014.IB',  cgbcr: '—',    cdb: '—',         cdbcr: '—'    },
    { tenor: '30Y',  cgb: '2500002.IB', cgbcr: '—',    cdb: '—',         cdbcr: '—'    },
  ];

  // ── Bond Futures & CTD ────────────────────────────────────────────────────
  const futCols = [
    { key: 'contract', label: 'Contract', align: 'left' },
    { key: 'close',    label: 'Close'  },
    { key: 'ctd',      label: 'CTD'    },
    { key: 'irr',      label: 'IRR'    },
    { key: 'zscore',   label: 'Zscore', render: (v) => <BarCell value={v} max={3} /> },
  ];
  const futRows = [
    { contract: 'TS2509', close: '103.248', ctd: '230022.IB', irr: '1.2841', zscore: -0.82 },
    { contract: 'TF2509', close: '105.760', ctd: '240013.IB', irr: '1.1904', zscore:  0.41 },
    { contract: 'T2509',  close: '107.625', ctd: '260005.IB', irr: '1.1522', zscore:  1.23 },
    { contract: 'TL2509', close: '118.940', ctd: '210014.IB', irr: '0.9831', zscore:  0.67 },
  ];

  // ── IRS Forward Rates — 6-col layout matching Python output ──────────────
  // Shifted column headers update dynamically to match real app behaviour
  const r7dLabel = `R7D++${Math.abs(r7dShift).toFixed(2)}BP`;
  const s3mLabel = `S3M++${Math.abs(s3mShift).toFixed(2)}BP`;

  // Left-anchored gradient bar (mirrors _bar_styles_gradient in Python)
  function GradBar({ value, min = 1.42, max = 1.65 }) {
    if (value === '—' || value == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
    const pct = Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
    return (
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', minHeight: '18px' }}>
        <div style={{ position: 'absolute', left: 0, top: '2px', bottom: '2px', width: `${pct}%`, background: 'rgba(31,58,94,0.65)', borderRadius: '1px' }} />
        <span style={{ position: 'relative', color: 'var(--text-primary)', padding: '0 6px' }}>{Number(value).toFixed(4)}</span>
      </div>
    );
  }

  const fwdBaseRows = [
    { term: 'Today', date: '20260621', r7d: 1.4800, s3m: 1.4300 },
    { term: '7D',    date: '20260628', r7d: 1.4775, s3m: 1.4339 },
    { term: '14D',   date: '20260705', r7d: 1.4748, s3m: 1.4364 },
    { term: '1M',    date: '20260721', r7d: 1.4695, s3m: 1.4417 },
    { term: '2M',    date: '20260821', r7d: 1.4599, s3m: 1.4527 },
    { term: '3M',    date: '20260921', r7d: 1.4521, s3m: 1.4620 },
    { term: '4M',    date: '20261021', r7d: 1.4459, s3m: 1.4595 },
    { term: '5M',    date: '20261121', r7d: 1.4411, s3m: 1.4582 },
    { term: '6M',    date: '20261221', r7d: 1.4375, s3m: 1.4579 },
    { term: '7M',    date: '20270121', r7d: 1.4350, s3m: 1.4587 },
    { term: '8M',    date: '20270221', r7d: 1.4336, s3m: 1.4604 },
    { term: '9M',    date: '20270321', r7d: 1.4332, s3m: 1.4627 },
    { term: '10M',   date: '20270421', r7d: 1.4336, s3m: 1.4658 },
    { term: '11M',   date: '20270521', r7d: 1.4347, s3m: 1.4696 },
    { term: '12M',   date: '20270621', r7d: 1.4365, s3m: 1.4740 },
  ];

  const fwdRows = fwdBaseRows.map(row => ({
    ...row,
    r7dShifted: +(row.r7d + r7dShift / 100).toFixed(4),
    s3mShifted: +(row.s3m + s3mShift / 100).toFixed(4),
  }));

  const fwdCols = [
    { key: 'term',       label: 'Term',     align: 'left' },
    { key: 'date',       label: 'Date'      },
    { key: 'r7d',        label: 'R7D Fwd',  render: (v) => <GradBar value={v} /> },
    { key: 'r7dShifted', label: r7dLabel,   render: (v) => <GradBar value={v} /> },
    { key: 's3m',        label: 'S3M Fwd',  render: (v) => <GradBar value={v} /> },
    { key: 's3mShifted', label: s3mLabel,   render: (v) => <GradBar value={v} /> },
  ];

  // ── Refresh button row ────────────────────────────────────────────────────
  const [timestamp, setTimestamp] = useState(() => {
    const n = new Date();
    return `Updated ${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')}:${String(n.getSeconds()).padStart(2,'0')}`;
  });
  function handleRefresh() {
    const n = new Date();
    setTimestamp(`Updated ${String(n.getHours()).padStart(2,'0')}:${String(n.getMinutes()).padStart(2,'0')}:${String(n.getSeconds()).padStart(2,'0')}`);
  }

  // ── IRS shift inputs (inline, matching an-card-actions row in Python) ─────
  const irsActions = (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
      <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>R7D shift (bp):</span>
      <input
        type="number"
        value={r7dShift}
        step={0.25}
        onChange={e => setR7dShift(parseFloat(e.target.value) || 0)}
        style={{
          width: '70px', fontSize: '12px', textAlign: 'right',
          background: 'var(--surface-input)', color: 'var(--text-primary)',
          border: '1px solid var(--accent-cyan)', borderRadius: '3px', padding: '2px 6px',
        }}
      />
      <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)', whiteSpace: 'nowrap', marginLeft: '10px' }}>S3M shift (bp):</span>
      <input
        type="number"
        value={s3mShift}
        step={0.25}
        onChange={e => setS3mShift(parseFloat(e.target.value) || 0)}
        style={{
          width: '70px', fontSize: '12px', textAlign: 'right',
          background: 'var(--surface-input)', color: 'var(--text-primary)',
          border: '1px solid var(--accent-cyan)', borderRadius: '3px', padding: '2px 6px',
        }}
      />
    </div>
  );

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '16px', marginBottom: '18px' }}>
        <h1 style={{ margin: 0, font: 'var(--type-h1)', color: 'var(--text-primary)' }}>Market Data Snapshot</h1>
        <Button variant="outline" accent="cyan" size="sm" icon="↻" onClick={handleRefresh}>Refresh</Button>
        <span style={{ font: 'var(--type-meta)', color: 'var(--text-muted)' }}>{timestamp}</span>
      </div>

      {/* 2-column grid */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', alignItems: 'start' }}>

        {/* ── Left column ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <Panel eyebrow="Money Market Rates" accent="cyan" padding="0">
            <DataTable columns={mmCols} rows={mmRows} />
          </Panel>
          <Panel eyebrow="Reference Bonds" accent="cyan" padding="0">
            <DataTable columns={refCols} rows={refRows} />
          </Panel>
          <Panel eyebrow="Bond Futures &amp; CTD" accent="cyan" padding="0">
            <DataTable columns={futCols} rows={futRows} />
          </Panel>
        </div>

        {/* ── Right column ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <Panel eyebrow="On-the-run Bonds" accent="cyan" padding="0">
            <DataTable columns={otrCols} rows={otrRows} />
          </Panel>
          <Panel eyebrow="IRS Forward Rates" accent="cyan" actions={irsActions} padding="0">
            <DataTable columns={fwdCols} rows={fwdRows} />
          </Panel>
        </div>

      </div>
    </div>
  );
}
window.MarketData = MarketData;
