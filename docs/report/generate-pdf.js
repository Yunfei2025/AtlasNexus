const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');

async function generatePDF() {
  try {
    const browser = await puppeteer.launch({
      headless: 'new',
      args: ['--disable-dev-shm-usage'],
    });

    const page = await browser.newPage();

    // Read the generated HTML
    const htmlPath = path.join(__dirname, 'generated-report.html');
    const html = fs.readFileSync(htmlPath, 'utf8');

    // Set the page content
    await page.setContent(html, { waitUntil: 'networkidle0' });

    // Wait for any custom fonts to load
    await page.waitForTimeout(500);

    // Generate PDF with A4 landscape settings
    const pdfPath = path.join(__dirname, 'generated-report.pdf');
    await page.pdf({
      path: pdfPath,
      format: 'A4',
      landscape: true,
      margin: { top: 0, right: 0, bottom: 0, left: 0 },
      printBackground: true,
      preferCSSPageSize: true,
    });

    await browser.close();

    console.log(`✓ PDF generated: ${pdfPath}`);
  } catch (error) {
    console.error('Error generating PDF:', error);
    process.exit(1);
  }
}

generatePDF();
