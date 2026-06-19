# FICC Monthly Report Generator

A system to generate professional monthly reports from structured data with PDF export capability.

## Quick Start

### 1. Setup (one-time)
```bash
# Copy the package.json
cp report-package.json package.json

# Install dependencies
npm install
```

### 2. Update Data
Edit `report-data.json` with your monthly data:
- KPI values (returns, NAV, drawdown, Sharpe ratio, rebalance date)
- Asset allocation (weights, changes, colors)
- Return figures for each asset class
- Risk contribution percentages
- Commentary bullet points

### 3. Generate Report
```bash
# Generate HTML only
npm run generate
# Output: generated-report.html

# Generate HTML + PDF
npm run pdf
# Output: generated-report.html + generated-report.pdf
```

## File Structure

| File | Purpose |
|------|---------|
| `report-data.json` | All your monthly data in one place |
| `report-template.html` | HTML template with placeholders |
| `generate-report.js` | Script to inject data into template |
| `generate-pdf.js` | Script to convert HTML to PDF |

## Data Format

### KPIs
```json
{
  "kpis": [
    {
      "label": "Display label",
      "value": "+0.62%",
      "valueClass": "pos|neg|''",
      "delta": "Sub-label",
      "accent": true/false
    }
  ]
}
```

### Asset Allocation
```json
{
  "allocation": {
    "effectiveDate": "2026-05-04",
    "segments": [
      {
        "name": "CN10Y 国债",
        "value": 20.1,        // percentage
        "color": "#0B2447",   // hex color
        "group": "固定收益",
        "change": "+1.4pp"
      }
    ]
  }
}
```

### Asset Returns
```json
{
  "returns": [
    {
      "group": "固定收益",
      "items": [
        {
          "asset": "CN1Y",
          "return": "+0.08%",
          "barWidth": 6,         // % for visual bar
          "returnClass": "pos|neg"
        }
      ]
    }
  ]
}
```

### Commentary
```json
{
  "commentary": [
    {
      "marker": "①",
      "text": "Your insight here..."
    }
  ]
}
```

## Customization

### Color Scheme
Edit `report-template.html` CSS variables to change colors:
```css
:root {
  --navy: #0B2447;
  --accent: #2EC4B6;
  --red: #D7595B;
  /* etc */
}
```

### Layout
The template uses CSS Grid. Key sections:
- `.page`: Main page container (A4 landscape, 297mm × 210mm)
- `.kpi-row`: 6-column KPI grid
- `.main`: 3-column main layout (allocation, returns, right-col)
- `.panel`: Individual content boxes

### Chart Data (Advanced)
For the 12-month NAV trend chart, update the SVG polyline points in `report-template.html`:
```html
<polyline ... points="0,72 25,68 50,70 ... 300,10" />
```
Points format: x,y coordinates where y increases downward.

## Tips

1. **Update only data**: Never edit the HTML placeholders in the template
2. **Test colors**: Use a hex color picker and update `report-data.json`
3. **PDF font rendering**: The template uses web-safe fonts + system Chinese fonts
4. **Audit bars**: `barWidth` in returns controls the visual bar length (0-100)
5. **Group totals**: Legend automatically calculates group sums from segment values

## Troubleshooting

**PDF looks different from HTML?**
- Use `preferCSSPageSize: true` to respect @page CSS rules
- Check that all fonts are installed on the system

**Chinese characters not rendering?**
- Ensure fonts are installed: "Source Han Sans SC", "Noto Sans SC", "PingFang SC"
- Puppeteer will fall back to system fonts

**Script fails?**
- Check Node.js version >= 14
- Run `npm install` again
- Clear browser cache: `rm -rf node_modules/.puppeteer-cache`

## License
Internal use only.
