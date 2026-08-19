const fs = require('fs');
const path = require('path');

const DELIM = '|';

// --- Parse pengumuman HTML ---
function parsePengumuman(html) {
  const result = {
    kode_rup: '',
    nama_paket: '',
    tanggal_pembuatan: '',
    k_l_pd_instansi_lainnya: '',
    satuan_kerja: '',
    tahun_anggaran: '',
    nilai_hps_paket: '',
    jenis_kontrak: '',
    lokasi_pekerjaan: '',
  };

  // Extract text content helper
  const getText = (regex) => {
    const m = html.match(regex);
    return m ? m[1].replace(/\s+/g, ' ').trim() : '';
  };

  // Kode RUP and Nama Paket (in sub-table inside "Rencana Umum Pengadaan")
  // Pattern: Kode RUP in first td, Nama Paket in second td
  const rupMatch = html.match(/Kode RUP[\s\S]*?<td[^>]*>(\d+)<\/td>[\s\S]*?<td[^>]*>([\s\S]*?)<\/td>[\s\S]*?<td[^>]*>([\s\S]*?)<\/td>/);
  if (rupMatch) {
    result.kode_rup = rupMatch[1].trim();
    result.nama_paket = cleanHtml(rupMatch[2]);
  }

  // Tanggal Pembuatan
  result.tanggal_pembuatan = cleanHtml(getText(/Tanggal Pembuatan<\/th>[\s\S]*?<td[^>]*>([\s\S]*?)<\/td>/i));

  // K/L/PD/Instansi Lainnya
  result.k_l_pd_instansi_lainnya = cleanHtml(getText(/K\/L\/PD\/Instansi Lainnya<\/th>[\s\S]*?<td[^>]*>([\s\S]*?)<\/td>/i));

  // Satuan Kerja
  result.satuan_kerja = cleanHtml(getText(/Satuan Kerja<\/th>[\s\S]*?<td[^>]*>([\s\S]*?)<\/td>/i));

  // Tahun Anggaran
  result.tahun_anggaran = cleanHtml(getText(/Tahun Anggaran<\/th>[\s\S]*?<td[^>]*>([\s\S]*?)<\/td>/i));

  // Nilai HPS Paket (it's in a row with Nilai Pagu - HPS is the second td)
  const hpsMatch = html.match(/Nilai HPS Paket<\/th>[\s\S]*?<td[^>]*>([\s\S]*?)<\/td>/i);
  if (hpsMatch) {
    result.nilai_hps_paket = cleanHtml(hpsMatch[1]);
  }

  // Jenis Kontrak
  result.jenis_kontrak = cleanHtml(getText(/Jenis Kontrak<\/th>[\s\S]*?<td[^>]*>([\s\S]*?)<\/td>/i));

  // Lokasi Pekerjaan (from <ul><li>...</li></ul>)
  const lokasiMatch = html.match(/Lokasi Pekerjaan<\/th>[\s\S]*?<td[^>]*>([\s\S]*?)<\/td>/i);
  if (lokasiMatch) {
    const liMatch = lokasiMatch[1].match(/<li>([\s\S]*?)<\/li>/);
    result.lokasi_pekerjaan = liMatch ? cleanHtml(liMatch[1]) : cleanHtml(lokasiMatch[1]);
  }

  return result;
}

// --- Parse peserta HTML ---
function parsePeserta(html) {
  const rows = [];
  // Match tbody rows
  const tbodyRegex = /<tbody>([\s\S]*?)<\/tbody>/i;
  const tbodyMatch = html.match(tbodyRegex);
  if (!tbodyMatch) return rows;

  const trRegex = /<tr>([\s\S]*?)<\/tr>/gi;
  let trMatch;
  while ((trMatch = trRegex.exec(tbodyMatch[1])) !== null) {
    const tr = trMatch[1];

    // Extract td values
    const tds = [];
    const tdRegex = /<td[^>]*>([\s\S]*?)<\/td>/gi;
    let tdMatch;
    while ((tdMatch = tdRegex.exec(tr)) !== null) {
      tds.push(tdMatch[1].replace(/\s+/g, ' ').trim());
    }

    if (tds.length >= 5) {
      rows.push({
        peserta_no: cleanHtml(tds[0]),
        peserta_nama: cleanHtml(tds[1]),
        peserta_npwp: cleanHtml(tds[2]),
        peserta_harga_penawaran: cleanHtml(tds[3]),
        peserta_harga_terkoreksi: cleanHtml(tds[4]),
      });
    }
  }
  return rows;
}

// --- Escape CSV field ---
function cleanHtml(val) {
  if (!val) return '';
  return val.replace(/<[^>]*>/g, '')   // strip tags
    .replace(/&nbsp;/gi, ' ')          // decode &nbsp;
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .replace(/&#(\d+);/g, (_, n) => String.fromCharCode(parseInt(n)))
    .replace(/\s+/g, ' ').trim();
}

function escapeField(val) {
  if (val == null) return '';
  const s = String(val);
  // If contains delimiter, quote, or newline, wrap in quotes
  if (s.includes(DELIM) || s.includes('"') || s.includes('\n') || s.includes('\r')) {
    return '"' + s.replace(/"/g, '""') + '"';
  }
  return s;
}

// --- Main ---
const jsonPath = path.join(__dirname, 'output', 'tender_2025.json');
const pengumumanDir = path.join(__dirname, 'output', 'html', 'tender', 'pengumuman');
const pesertaDir = path.join(__dirname, 'output', 'html', 'tender', 'peserta');

const jsonData = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));
console.log(`Loaded ${jsonData.length} JSON items`);

// Index HTML files by kode prefix
function indexHtmlDir(dir) {
  const files = fs.readdirSync(dir);
  const index = {};
  for (const f of files) {
    if (!f.endsWith('.html')) continue;
    const kode = f.split('_')[0];
    index[kode] = path.join(dir, f);
  }
  return index;
}

const pengumumanIndex = indexHtmlDir(pengumumanDir);
console.log(`Indexed ${Object.keys(pengumumanIndex).length} pengumuman HTML files`);

const pesertaIndex = indexHtmlDir(pesertaDir);
console.log(`Indexed ${Object.keys(pesertaIndex).length} peserta HTML files`);

// Define columns
const jsonKeys = ['kode', 'nama', 'instansi', 'status', 'nilai_pagu', 'kualifikasi', 'metode_pemilihan', 'evaluasi', 'jenis_pengadaan', 'peserta', 'nilai_kontrak'];
const pengumumanKeys = ['kode_rup', 'nama_paket', 'tanggal_pembuatan', 'k_l_pd_instansi_lainnya', 'satuan_kerja', 'tahun_anggaran', 'nilai_hps_paket', 'jenis_kontrak', 'lokasi_pekerjaan'];
const pesertaKeys = ['peserta_no', 'peserta_nama', 'peserta_npwp', 'peserta_harga_penawaran', 'peserta_harga_terkoreksi'];

const allColumns = [...jsonKeys, ...pengumumanKeys, ...pesertaKeys];

// Build rows
const rows = [];
let matchedPengumuman = 0;
let matchedPeserta = 0;
let totalPesertaRows = 0;

for (const item of jsonData) {
  const kode = String(item.kode);
  const baseRow = {};

  // JSON fields - strip HTML tags from nama
  for (const key of jsonKeys) {
    let val = item[key] || '';
    if (key === 'nama') val = cleanHtml(val);
    baseRow[key] = val;
  }

  // Pengumuman fields
  const pengumumanFile = pengumumanIndex[kode];
  if (pengumumanFile) {
    matchedPengumuman++;
    const html = fs.readFileSync(pengumumanFile, 'utf-8');
    const parsed = parsePengumuman(html);
    for (const key of pengumumanKeys) {
      baseRow[key] = parsed[key] || '';
    }
  } else {
    for (const key of pengumumanKeys) {
      baseRow[key] = '';
    }
  }

  // Peserta fields
  const pesertaFile = pesertaIndex[kode];
  const pesertaRows = [];
  if (pesertaFile) {
    matchedPeserta++;
    const html = fs.readFileSync(pesertaFile, 'utf-8');
    const parsed = parsePeserta(html);
    for (const pRow of parsed) {
      const row = { ...baseRow };
      for (const key of pesertaKeys) {
        row[key] = pRow[key] || '';
      }
      pesertaRows.push(row);
      totalPesertaRows++;
    }
  }

  if (pesertaRows.length > 0) {
    rows.push(...pesertaRows);
  } else {
    // No peserta - just JSON + pengumuman, peserta columns empty
    const row = { ...baseRow };
    for (const key of pesertaKeys) {
      row[key] = '';
    }
    rows.push(row);
  }
}

console.log(`\nMatched pengumuman: ${matchedPengumuman}/${jsonData.length}`);
console.log(`Matched peserta: ${matchedPeserta}/${jsonData.length}`);
console.log(`Total peserta rows: ${totalPesertaRows}`);
console.log(`Total CSV rows: ${rows.length}`);

// Write CSV
const header = allColumns.map(escapeField).join(DELIM);
const csvLines = [header];
for (const row of rows) {
  const line = allColumns.map(col => escapeField(row[col] || '')).join(DELIM);
  csvLines.push(line);
}

const outputPath = path.join(__dirname, 'output', 'tender_2025.csv');
fs.writeFileSync(outputPath, csvLines.join('\n'), 'utf-8');
console.log(`\nWritten to: ${outputPath}`);
