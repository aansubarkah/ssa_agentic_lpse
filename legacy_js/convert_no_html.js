const fs = require('fs');
const path = require('path');
const ExcelJS = require('exceljs');

const DELIM = '|';
const jsonData = JSON.parse(fs.readFileSync(path.join(__dirname, 'output', 'tender_2025.json'), 'utf-8'));
const pengumumanDir = path.join(__dirname, 'output', 'html', 'tender', 'pengumuman');
const pesertaDir = path.join(__dirname, 'output', 'html', 'tender', 'peserta');

const pCodes = new Set(fs.readdirSync(pengumumanDir).map(f => f.split('_')[0]));
const sCodes = new Set(fs.readdirSync(pesertaDir).map(f => f.split('_')[0]));

// Items with NO HTML at all (no pengumuman AND no peserta)
const noHtml = jsonData.filter(d => !pCodes.has(String(d.kode)) && !sCodes.has(String(d.kode)));
console.log(`Found ${noHtml.length} items with no HTML`);

// JSON keys only (since there's no HTML to parse)
const columns = ['kode', 'nama', 'instansi', 'status', 'nilai_pagu', 'kualifikasi', 'metode_pemilihan', 'evaluasi', 'jenis_pengadaan', 'peserta', 'nilai_kontrak'];

// Clean HTML tags from values
function clean(val) {
  if (!val) return '';
  return String(val).replace(/<[^>]*>/g, '').replace(/&nbsp;/gi, ' ').replace(/\s+/g, ' ').trim();
}

function escapeField(val) {
  if (!val) return '';
  const s = String(val);
  if (s.includes(DELIM) || s.includes('"') || s.includes('\n') || s.includes('\r')) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

// Prepare rows
const rows = noHtml.map(d => {
  const row = {};
  for (const key of columns) {
    row[key] = key === 'nama' ? clean(d[key]) : (d[key] || '');
  }
  return row;
});

// --- Write CSV ---
const header = columns.map(escapeField).join(DELIM);
const csvLines = [header, ...rows.map(r => columns.map(c => escapeField(r[c])).join(DELIM))];
const csvPath = path.join(__dirname, 'output', 'tender_2025_no_html.csv');
fs.writeFileSync(csvPath, csvLines.join('\n'), 'utf-8');
console.log(`CSV: ${csvPath}`);

// --- Write Excel (.xlsx) ---
const wb = new ExcelJS.Workbook();
const ws = wb.addWorksheet('No HTML');

// Header row
ws.addRow(columns);
// Style header
ws.getRow(1).font = { bold: true };
ws.getRow(1).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFE0E0E0' } };

// Data rows
for (const row of rows) {
  ws.addRow(columns.map(c => row[c]));
}

// Auto-fit columns (approximate)
ws.columns.forEach((col, i) => {
  let maxLen = columns[i].length;
  for (let r = 2; r <= ws.rowCount; r++) {
    const val = ws.getCell(r, i + 1).value;
    if (val) maxLen = Math.max(maxLen, String(val).length);
  }
  col.width = Math.min(maxLen + 2, 60);
});

const xlsxPath = path.join(__dirname, 'output', 'tender_2025_no_html.xlsx');
wb.xlsx.writeFile(xlsxPath).then(() => {
  console.log(`Excel: ${xlsxPath}`);
});
