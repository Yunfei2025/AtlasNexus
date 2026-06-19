const fs = require('fs');
const path = require('path');

// Read the data config
const dataPath = path.join(__dirname, 'report-data.json');
const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));

// Read the template
const templatePath = path.join(__dirname, 'report-template.html');
const template = fs.readFileSync(templatePath, 'utf8');

// Helper to render KPI row
function renderKPIs() {
  return data.kpis.map(kpi => `
    <div class="kpi${kpi.accent ? ' accent' : ''}">
      <div class="label">${kpi.label}</div>
      <div class="value${kpi.valueClass ? ' ' + kpi.valueClass : ''}"${kpi.label === '本月再平衡' ? ' style="font-size:12.5pt;"' : ''}>${kpi.value}</div>
      <div class="delta">${kpi.delta}</div>
    </div>
  `).join('');
}

// Helper to render allocation donut SVG circles (simplified)
function renderDonutCircles() {
  return `
    <circle cx="21" cy="21" r="15.9" fill="transparent" stroke="#EDEFF3" stroke-width="6"></circle>
    <circle cx="21" cy="21" r="15.9" fill="transparent" stroke="#0B2447" stroke-width="6"
            stroke-dasharray="20.1 79.8" stroke-dashoffset="25"></circle>
    <circle cx="21" cy="21" r="15.9" fill="transparent" stroke="#2E4D7B" stroke-width="6"
            stroke-dasharray="17.0 82.9" stroke-dashoffset="4.9"></circle>
    <circle cx="21" cy="21" r="15.9" fill="transparent" stroke="#2EC4B6" stroke-width="6"
            stroke-dasharray="28.6 71.3" stroke-dashoffset="-12.1"></circle>
    <circle cx="21" cy="21" r="15.9" fill="transparent" stroke="#E0A458" stroke-width="6"
            stroke-dasharray="11.4 88.5" stroke-dashoffset="-40.7"></circle>
    <circle cx="21" cy="21" r="15.9" fill="transparent" stroke="#C97B3D" stroke-width="6"
            stroke-dasharray="6.7 93.2" stroke-dashoffset="-52.1"></circle>
    <text x="21" y="19.6" text-anchor="middle" font-size="4.6" fill="#0B2447" font-weight="700">100%</text>
    <text x="21" y="24.4" text-anchor="middle" font-size="2.7" fill="#5B6B82">配置中</text>
  `;
}

// Helper to render allocation legend
function renderAllocationLegend() {
  let html = '';
  let currentGroup = '';

  data.allocation.segments.forEach(seg => {
    if (seg.group !== currentGroup) {
      currentGroup = seg.group;
      const groupTotal = data.allocation.segments
        .filter(s => s.group === currentGroup)
        .reduce((sum, s) => sum + s.value, 0);
      html += `<div class="grp-label">${currentGroup} · ${groupTotal.toFixed(1)}%</div>`;
    }
    html += `
      <div class="row">
        <span class="dot" style="background:${seg.color}"></span>
        <span class="nm">${seg.name}</span>
        <span class="pct">${seg.value}%</span>
        <span class="chg">${seg.change}</span>
      </div>
    `;
  });

  return html;
}

// Helper to render returns table
function renderReturnsTable() {
  let html = '<thead><tr><th>资产</th><th class="num">月收益</th><th>贡献 / 方向</th></tr></thead><tbody>';

  data.returns.forEach(group => {
    html += `<tr class="grp"><td colspan="3">${group.group}</td></tr>`;
    group.items.forEach(item => {
      html += `
        <tr>
          <td>${item.asset}</td>
          <td class="num ${item.returnClass}">${item.return}</td>
          <td class="bar-cell"><div class="bar-track"><div class="bar-mid"></div><div class="bar-fill ${item.returnClass}" style="width:${item.barWidth}%"></div></div></td>
        </tr>
      `;
    });
  });

  html += '</tbody>';
  return html;
}

// Helper to render risk contribution
function renderRiskContribution() {
  return data.riskContribution.map(risk => `
    <div class="riskbar-row">
      <span>${risk.name}</span>
      <div class="riskbar-track"><div class="riskbar-fill" style="width:${risk.percentage}%; background:${risk.color};"></div></div>
      <span>${risk.percentage}%</span>
    </div>
  `).join('');
}

// Helper to render commentary
function renderCommentary() {
  return data.commentary.map(item => `
    <div class="dot-item">
      <span class="marker">${item.marker}</span>
      <span>${item.text}</span>
    </div>
  `).join('');
}

// Replace all placeholders
let html = template
  .replace('{{reportMonth}}', data.report.reportMonth)
  .replace('{{reportPeriod}}', data.report.reportPeriod)
  .replace('{{publishDate}}', data.report.publishDate)
  .replace('{{kpiRows}}', renderKPIs())
  .replace('{{allocationEffectiveDate}}', data.allocation.effectiveDate)
  .replace('{{donutSVG}}', renderDonutCircles())
  .replace('{{allocationLegend}}', renderAllocationLegend())
  .replace('{{returnsTable}}', renderReturnsTable())
  .replace('{{riskContribution}}', renderRiskContribution())
  .replace('{{commentary}}', renderCommentary());

// Write the final report
const outputPath = path.join(__dirname, 'generated-report.html');
fs.writeFileSync(outputPath, html);

console.log(`✓ Report generated: ${outputPath}`);
