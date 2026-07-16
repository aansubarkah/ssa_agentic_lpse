const fs = require('fs');
const path = require('path');
const ExcelJS = require('exceljs');

const csvPath = path.join(__dirname, 'output', 'tender_2025.csv');
const xlsxPath = path.join(__dirname, 'output', 'tender_2025.xlsx');

const DELIM = '|';
const raw = fs.readFileSync(csvPath, 'utf-8');
const lines = raw.split(/\r?\n/).filter(l => l.length > 0);

// Parse CSV respecting quoted fields
function parseLine(line) {
  const fields = [];
  let current = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"' && line[i + 1] === '"') {
        current += '"';
        i++;
      } else if (ch === '"') {
        inQuotes = false;
      } else {
        current += ch;
      }
    } else {
      if (ch === '"') {
        inQuotes = true;
      } else if (ch === DELIM) {
        fields.push(current);
        current = '';
      } else {
        current += ch;
      }
    }
  }
  fields.push(current);
  return fields;
}

const headers = parseLine(lines[0]);
console.log(`Columns: ${headers.length}, Rows: ${lines.length - 1}`);

const wb = new ExcelJS.Workbook();
const ws = wb.addWorksheet('Tender 2025');

// Header
ws.addRow(headers);
const headerRow = ws.getRow(1);
headerRow.font = { bold: true };
headerRow.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF4472C4' } };
headerRow.font = { bold: true, color: { argb: 'FFFFFFFF' } };
headerRow.alignment = { horizontal: 'center', vertical: 'middle', wrapText: true };
headerRow.height = 30;

// Freeze pane below header
ws.views = [{ state: 'frozen', ySplit: 1 }];

// Data rows
let colWidths = headers.map(h => h.length);

for (let i = 1; i < lines.length; i++) {
  const fields = parseLine(lines[i]);
  if (fields.length !== headers.length) {
    console.warn(`Row ${i + 1}: field count ${fields.length} != ${headers.length}, skipping`);
    continue;
  }
  ws.addRow(fields);
  for (let j = 0; j < fields.length; j++) {
    colWidths[j] = Math.max(colWidths[j], fields[j].length);
  }
  if ((i + 1) % 2000 === 0) console.log(`  Processed ${i + 1}/${lines.length - 1} rows`);
}

// Auto-fit column widths (capped at 60)
ws.columns.forEach((col, idx) => {
  col.width = Math.min(colWidths[idx] + 2, 60);
});

// Add autofilter
ws.autoFilter = {
  from: { row: 1, column: 1 },
  to: { row: lines.length, column: headers.length },
};

wb.xlsx.writeFile(xlsxPath).then(() => {
  console.log(`\nDone: ${xlsxPath}`);
  const stats = fs.statSync(xlsxPath);
  console.log(`Size: ${(stats.size / 1024 / 1024).toFixed(1)} MB`);
});
