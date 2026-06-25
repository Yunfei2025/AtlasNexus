// Run Center — daily pipeline, data backfill, status & logs.
const _ns_rc = window.AtlasNexusDesignSystem_988df3;

const MOCK_LOGS = [
  { t: '13:08:58', level: 'INFO',  msg: 'run_id=20260617-eod-210752 | mode=eod | asof=2026-06-17 | started' },
  { t: '13:08:58', level: 'INFO',  msg: 'Loading instrument pool...' },
  { t: '13:09:01', level: 'INFO',  msg: 'Pool loaded: 312 instruments (Bonds: 198, IRS: 56, Futures: 41, FX: 17)' },
  { t: '13:09:02', level: 'INFO',  msg: 'Fetching market data from source...' },
  { t: '13:09:07', level: 'WARN',  msg: '260005.IB — missing close price, using prior day' },
  { t: '13:09:09', level: 'INFO',  msg: 'Market data fetch complete (309/312)' },
  { t: '13:09:09', level: 'INFO',  msg: 'Running factor model update...' },
  { t: '13:09:14', level: 'INFO',  msg: 'Factor series updated: DUR, CONV, CS01, DV01' },
  { t: '13:09:14', level: 'INFO',  msg: 'Running EOD pricing...' },
  { t: '13:09:21', level: 'INFO',  msg: 'Priced 312 instruments' },
  { t: '13:09:21', level: 'INFO',  msg: 'Computing P&L attribution...' },
  { t: '13:09:25', level: 'INFO',  msg: 'P&L complete | total_pnl=+2,184,330 | carry=+412,100 | price=+1,772,230' },
  { t: '13:09:25', level: 'INFO',  msg: 'Updating risk metrics...' },
  { t: '13:09:29', level: 'INFO',  msg: 'DV01=8.29 MM/bp | Duration=7.42y | Net=+9,924 MM' },
  { t: '13:09:29', level: 'INFO',  msg: 'Writing output to store...' },
  { t: '13:09:30', level: 'INFO',  msg: 'Snapshot saved: eod_20260617.parquet' },
  { t: '13:09:30', level: 'INFO',  msg: 'Run complete | elapsed=32.4s | status=completed' },
];

const LEVEL_COLOR = { INFO: '#4a9eff', WARN: '#e0a23c', ERROR: '#e05c5c', DEBUG: '#6b7fa0' };

function RunCenter() {
  const { useState, useEffect, useRef } = React;
  const { Panel, Button, Input, Select } = _ns_rc;

  const [logs, setLogs] = useState(MOCK_LOGS);
  const [running, setRunning] = useState(false);
  const [lastRun, setLastRun] = useState({ id: '20260617-eod-210752', status: 'completed', asof: '2026-06-17', elapsed: '32.4s' });
  const [asofDate, setAsofDate] = useState('2026-06-18');
  const [instType, setInstType] = useState('IRS');
  const [updateStep, setUpdateStep] = useState('ALL');
  const [startDate, setStartDate] = useState('2026-03-18');
  const [endDate, setEndDate] = useState('2026-06-18');
  const [workers, setWorkers] = useState('4');
  const logRef = useRef(null);

  const now = () => {
    const d = new Date();
    return `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}:${String(d.getSeconds()).padStart(2,'0')}`;
  };

  const addLog = (level, msg) => setLogs(prev => [...prev, { t: now(), level, msg }]);
  const clearLogs = () => setLogs([]);

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs]);

  const simulateRun = (mode) => {
    if (running) return;
    setRunning(true);
    const runId = `${asofDate.replace(/-/g,'')}${mode === 'eod' ? '-eod' : '-update'}-${now().replace(/:/g,'')}`;
    addLog('INFO', `run_id=${runId} | mode=${mode} | asof=${asofDate} | started`);

    const steps = mode === 'update' ? [
      [400,  'INFO',  'Connecting to data sources...'],
      [900,  'INFO',  'Fetching market data (Bonds)...'],
      [1500, 'INFO',  'Fetching market data (IRS)...'],
      [2200, 'INFO',  'Fetching market data (Futures, FX)...'],
      [2800, 'INFO',  `Market data updated | 309 instruments | elapsed=2.8s`],
      [3000, 'INFO',  `Data update complete | status=completed`],
    ] : [
      [300,  'INFO',  'Loading instrument pool...'],
      [800,  'INFO',  'Pool loaded: 312 instruments'],
      [900,  'INFO',  'Fetching market data from source...'],
      [1600, 'WARN',  `${asofDate === '2026-06-18' ? '260005.IB' : '250012.IB'} — stale price, using interpolation`],
      [2100, 'INFO',  'Market data fetch complete'],
      [2200, 'INFO',  'Running factor model update...'],
      [2900, 'INFO',  'Factor series updated: DUR, CONV, CS01, DV01'],
      [3000, 'INFO',  'Running EOD pricing...'],
      [3800, 'INFO',  'Priced 312 instruments'],
      [3900, 'INFO',  'Computing P&L attribution...'],
      [4500, 'INFO',  'P&L complete | carry=+412,100 | price=+1,772,230'],
      [4600, 'INFO',  'Updating risk metrics...'],
      [5200, 'INFO',  'DV01=8.29 MM/bp | Duration=7.42y'],
      [5300, 'INFO',  'Writing output to store...'],
      [5600, 'INFO',  `Run complete | elapsed=${mode === 'both' ? '5.6' : '5.6'}s | status=completed`],
    ];

    steps.forEach(([delay, level, msg]) => {
      setTimeout(() => addLog(level, msg), delay);
    });

    const totalDelay = steps[steps.length - 1][0] + 200;
    setTimeout(() => {
      setRunning(false);
      setLastRun({ id: runId, status: 'completed', asof: asofDate, elapsed: `${(steps[steps.length-1][0]/1000).toFixed(1)}s` });
    }, totalDelay);
  };

  const simulateBackfill = () => {
    if (running) return;
    setRunning(true);
    const runId = `${startDate.replace(/-/g,'')}_${endDate.replace(/-/g,'')}-backfill-${now().replace(/:/g,'')}`;
    addLog('INFO', `run_id=${runId} | mode=backfill | type=${instType} | steps=${updateStep} | workers=${workers}`);

    const dayCount = Math.min(Math.round((new Date(endDate) - new Date(startDate)) / 86400000), 65);
    const steps = [
      [200,  'INFO',  `Date range: ${startDate} → ${endDate} (${dayCount} business days)`],
      [500,  'INFO',  `Worker pool initialized: ${workers} workers`],
      [800,  'INFO',  `Processing ${instType} instruments...`],
      [1400, 'INFO',  `[1/${workers}] Processing batch 1/4...`],
      [2000, 'INFO',  `[2/${workers}] Processing batch 2/4...`],
      [2600, 'INFO',  `[3/${workers}] Processing batch 3/4...`],
      [3200, 'INFO',  `[4/${workers}] Processing batch 4/4...`],
      [3800, 'INFO',  `All batches complete | ${dayCount} days × ${instType} | step=${updateStep}`],
      [4200, 'INFO',  `Generating factor series...`],
      [4800, 'INFO',  `Factor series written | elapsed=${(4.8).toFixed(1)}s | status=completed`],
    ];

    steps.forEach(([delay, level, msg]) => {
      setTimeout(() => addLog(level, msg), delay);
    });
    setTimeout(() => {
      setRunning(false);
      setLastRun({ id: runId, status: 'completed', asof: `${startDate}→${endDate}`, elapsed: '4.8s' });
    }, steps[steps.length - 1][0] + 200);
  };

  const SectionLabel = ({ children }) => (
    <div style={{ font: 'var(--type-th)', letterSpacing: 'var(--ls-label)', textTransform: 'uppercase',
      color: 'var(--text-muted)', marginBottom: '14px', paddingBottom: '8px',
      borderBottom: '1px solid var(--border-subtle)' }}>
      {children}
    </div>
  );

  const FieldRow = ({ children }) => (
    <div style={{ display: 'flex', gap: '10px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
      {children}
    </div>
  );

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '380px 1fr', gap: '16px', alignItems: 'start' }}>

      {/* LEFT: Controls */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

        {/* Daily Pipeline */}
        <Panel padding="18px 20px">
          <SectionLabel>Daily Pipeline</SectionLabel>
          <Input label="As Of Date" value={asofDate} onChange={e => setAsofDate(e.target.value)}
            style={{ marginBottom: '14px', width: '100%' }} />
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <FieldRow>
              <Button variant="ghost" disabled={running} onClick={() => simulateRun('update')}
                style={{ flex: 1 }}>Update Data</Button>
              <Button variant="ghost" disabled={running} onClick={() => simulateRun('eod')}
                style={{ flex: 1 }}>Run EOD</Button>
            </FieldRow>
            <Button variant="ghost" disabled={running} onClick={() => { simulateRun('both'); }}
              style={{ width: '100%' }}>Run EOD + Update Data</Button>
            <Button variant="ghost" disabled={running}
              onClick={() => { addLog('INFO', 'Refreshing instrument registry...'); setTimeout(() => addLog('INFO', 'Instruments refreshed: 312 active'), 1200); }}
              style={{ width: '100%' }}>Refresh Instruments</Button>
          </div>
        </Panel>

        {/* Data Backfill */}
        <Panel padding="18px 20px">
          <SectionLabel>Data Backfill</SectionLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <FieldRow>
              <div style={{ flex: 1 }}>
                <Select label="Instrument Type" options={['IRS', 'Bond', 'Futures', 'FX', 'ALL']}
                  value={instType} onChange={e => setInstType(e.target.value)} />
              </div>
              <div style={{ flex: 1 }}>
                <Select label="Update Steps" options={['POOL', 'FACTOR', 'EOD', 'ALL']}
                  value={updateStep} onChange={e => setUpdateStep(e.target.value)} />
              </div>
            </FieldRow>
            <FieldRow>
              <div style={{ flex: 1 }}>
                <Input label="Start Date" value={startDate} onChange={e => setStartDate(e.target.value)} />
              </div>
              <div style={{ flex: 1 }}>
                <Input label="End Date" value={endDate} onChange={e => setEndDate(e.target.value)} />
              </div>
              <div style={{ width: '56px' }}>
                <Input label="Workers" value={workers} onChange={e => setWorkers(e.target.value)} />
              </div>
            </FieldRow>
            <Button accent="teal" disabled={running} onClick={simulateBackfill}
              style={{ width: '100%' }}>▶ Run Backfill</Button>
            <Button variant="outline" accent="green" disabled={running}
              onClick={() => { addLog('INFO', 'Generating factor series...'); setTimeout(() => addLog('INFO', 'Factor series complete | DUR, CONV, CS01, DV01'), 1800); }}
              style={{ width: '100%' }}>Generate Factor Series</Button>
          </div>
        </Panel>

      </div>

      {/* RIGHT: Status + Logs */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>

        {/* Status bar */}
        <Panel padding="14px 18px">
          <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{
                width: '8px', height: '8px', borderRadius: '50%',
                background: running ? '#e0a23c' : '#41b078',
                boxShadow: running ? '0 0 6px #e0a23c' : '0 0 6px #41b078',
              }} />
              <span style={{ font: 'var(--type-mono)', fontSize: '12px',
                color: running ? '#e0a23c' : '#41b078' }}>
                {running ? 'RUNNING' : 'IDLE'}
              </span>
            </div>
            {lastRun && (
              <span style={{ font: 'var(--type-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
                Last: {lastRun.id} | {lastRun.asof} | {lastRun.elapsed} | {lastRun.status}
              </span>
            )}
            <button onClick={clearLogs} style={{
              marginLeft: 'auto', background: 'none', border: '1px solid var(--border-subtle)',
              borderRadius: '4px', color: 'var(--text-muted)', font: 'var(--type-mono)',
              fontSize: '11px', padding: '3px 10px', cursor: 'pointer',
            }}>Clear</button>
          </div>
        </Panel>

        {/* Log viewer */}
        <Panel padding="0">
          <div ref={logRef} style={{
            height: '480px', overflowY: 'auto', padding: '14px 16px',
            fontFamily: '"IBM Plex Mono", "Courier New", monospace',
            fontSize: '12px', lineHeight: '1.7',
            background: 'rgba(4, 10, 22, 0.6)',
          }}>
            {logs.length === 0 && (
              <div style={{ color: 'var(--text-faint)', fontStyle: 'italic' }}>
                No logs. Start a job to see output here.
              </div>
            )}
            {logs.map((log, i) => (
              <div key={i} style={{ display: 'flex', gap: '10px', color: 'var(--text-secondary)' }}>
                <span style={{ color: 'var(--text-faint)', flexShrink: 0 }}>{log.t}</span>
                <span style={{ color: LEVEL_COLOR[log.level] || '#6b7fa0', flexShrink: 0, width: '42px' }}>
                  {log.level}
                </span>
                <span style={{ color: log.level === 'WARN' ? '#c8944a' : log.level === 'ERROR' ? '#d56b6b' : 'var(--text-secondary)' }}>
                  {log.msg}
                </span>
              </div>
            ))}
            {running && (
              <div style={{ display: 'flex', gap: '10px', color: 'var(--text-faint)' }}>
                <span style={{ color: 'var(--text-faint)' }}>{now()}</span>
                <span style={{ color: '#e0a23c', width: '42px' }}>…</span>
                <span style={{ animation: 'none' }}>running</span>
              </div>
            )}
          </div>
        </Panel>

      </div>
    </div>
  );
}
window.RunCenter = RunCenter;
