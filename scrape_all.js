/**
 * scrape_all.js — SPSE Kemkes 2025: Daftar Pekerjaan + Peserta/Pemenang + Pengumuman
 *
 * Usage:
 *   node scrape_all.js                  # full scrape (semua paket)
 *   node scrape_all.js --limit 5        # test: hanya 5 paket per kategori
 *   node scrape_all.js --skip-json      # skip scraping JSON, hanya HTML
 *   node scrape_all.js --skip-peserta   # skip HTML peserta/pemenang
 *   node scrape_all.js --skip-pengumuman# skip HTML pengumuman
 */
const fs = require('fs');
const path = require('path');
const https = require('https');
const { gunzipSync, inflateSync, brotliDecompressSync } = require('zlib');

// ============================================================
// CLI args
// ============================================================
const argv = process.argv.slice(2);
const LIMIT  = parseInt((argv.find(a => a.startsWith('--limit'))  || '').split('=')[1] || argv[argv.indexOf('--limit') + 1], 10) || 0;
const SKIP_JSON       = argv.includes('--skip-json');
const SKIP_PESERTA    = argv.includes('--skip-peserta');
const SKIP_PENGUMUMAN  = argv.includes('--skip-pengumuman');
const DRY_RUN = argv.includes('--dry');

// ============================================================
// Config
// ============================================================
const BASE = 'https://spse.inaproc.id/kemkes';
const ROOT = path.join(__dirname, 'output');
const JSON_DIR = ROOT;
const HTML_ROOT = path.join(ROOT, 'html');
const DELAY_MS = 600;
const PAGE_SIZE = 300;

const DIRS = {
  tenderPeserta:     path.join(HTML_ROOT, 'tender',     'peserta'),
  nonTenderPeserta:  path.join(HTML_ROOT, 'non_tender', 'peserta'),
  pencatatanPemenang: path.join(HTML_ROOT, 'pencatatan', 'pemenang'),
  tenderPengumuman:     path.join(HTML_ROOT, 'tender',     'pengumuman'),
  nonTenderPengumuman:  path.join(HTML_ROOT, 'non_tender', 'pengumuman'),
  pencatatanPengumuman: path.join(HTML_ROOT, 'pencatatan', 'pengumuman'),
};

// JSON output paths
const JSON_FILES = {
  tender:     path.join(JSON_DIR, 'tender_2025.json'),
  nonTender:  path.join(JSON_DIR, 'non_tender_2025.json'),
  pencatatan: path.join(JSON_DIR, 'pencatatan_non_tender_2025.json'),
};

// ============================================================
// HTTP helpers (shared)
// ============================================================
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0';

function doRequest(url, method, headers, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const opts = {
      hostname: u.hostname, path: u.pathname + u.search, method: method || 'GET',
      headers: { ...headers, Host: u.hostname },
    };
    const req = https.request(opts, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        const loc = res.headers.location;
        return doRequest(loc.startsWith('http') ? loc : `https://${u.hostname}${loc}`, method, headers, body)
          .then(resolve).catch(reject);
      }
      const chunks = [];
      const enc = res.headers['content-encoding'];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => {
        try {
          let buf = Buffer.concat(chunks);
          if (enc === 'gzip') buf = gunzipSync(buf);
          else if (enc === 'deflate') buf = inflateSync(buf);
          else if (enc === 'br') buf = brotliDecompressSync(buf);
          resolve({ status: res.statusCode, headers: res.headers, body: buf.toString('utf8') });
        } catch (e) { reject(e); }
      });
    });
    req.on('error', reject);
    if (body) req.write(body);
    req.end();
  });
}

class CookieJar {
  constructor() { this.jar = {}; }
  update(h) {
    for (const sc of (h || [])) {
      const [nv, ...attrs] = sc.split(';').map(s => s.trim());
      const idx = nv.indexOf('=');
      const name = nv.substring(0, idx).trim();
      const value = nv.substring(idx + 1);
      if (attrs.some(a => a.startsWith('Max-Age=0'))) delete this.jar[name];
      else if (value) this.jar[name] = value;
    }
  }
  toString() { return Object.entries(this.jar).map(([k, v]) => `${k}=${v}`).join('; '); }
}

function initSession(pageUrl) {
  return new Promise((resolve, reject) => {
    const u = new URL(pageUrl);
    https.request({
      hostname: u.hostname, path: u.pathname + u.search, method: 'GET',
      headers: { 'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Accept-Language': 'en-US,en;q=0.5', 'Host': u.hostname },
    }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        const loc = res.headers.location;
        return initSession(loc.startsWith('http') ? loc : `https://${u.hostname}${loc}`).then(resolve).catch(reject);
      }
      const chunks = [];
      const enc = res.headers['content-encoding'];
      res.on('data', c => chunks.push(c));
      res.on('end', () => {
        try {
          let buf = Buffer.concat(chunks);
          if (enc === 'gzip') buf = gunzipSync(buf);
          else if (enc === 'br') buf = brotliDecompressSync(buf);
          const html = buf.toString('utf8');
          const cookies = new CookieJar();
          cookies.update(res.headers['set-cookie']);
          const m = html.match(/authenticityToken\s*=\s*'([^']+)'/);
          resolve({ cookies, token: m ? m[1] : null });
        } catch (e) { reject(e); }
      });
    }).on('error', reject).end();
  });
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

// ============================================================
// Filename sanitization
// ============================================================
function safeName(raw) {
  return (raw || '')
    .replace(/<[^>]+>/g, '')
    .replace(/[\t\n\r]/g, ' ')
    .replace(/[\/\\:*?"<>|\0]/g, '-')
    .replace(/\s+/g, ' ')
    .trim()
    .substring(0, 80);
}

// ============================================================
// DataTables paginated fetch (for JSON data)
// ============================================================
function buildDtBody(token, draw, start, length, numCols) {
  const p = new URLSearchParams();
  p.append('draw', String(draw));
  p.append('start', String(start));
  p.append('length', String(length));
  p.append('search[value]', '');
  p.append('search[regex]', 'false');
  p.append('authenticityToken', token);
  for (let i = 0; i < numCols; i++) {
    p.append(`columns[${i}][data]`, String(i));
    p.append(`columns[${i}][name]`, '');
    p.append(`columns[${i}][searchable]`, 'true');
    p.append(`columns[${i}][orderable]`, 'true');
    p.append(`columns[${i}][search][value]`, '');
    p.append(`columns[${i}][search][regex]`, 'false');
  }
  p.append('order[0][column]', '0');
  p.append('order[0][dir]', 'asc');
  return p.toString();
}

async function fetchAllPages(apiUrl, refererUrl, token, cookies, numCols) {
  console.log(`  API: ${apiUrl}`);
  const allData = [];
  let draw = 1, start = 0, hasMore = true;

  while (hasMore) {
    const body = buildDtBody(token, draw, start, PAGE_SIZE, numCols);
    process.stdout.write(`    page draw=${draw} start=${start} ... `);

    try {
      const res = await doRequest(apiUrl, 'POST', {
        'User-Agent': UA,
        'Accept': 'application/json, text/javascript, */*; q=0.01',
        'Accept-Language': 'en-US,en;q=0.5',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'X-Requested-With': 'XMLHttpRequest',
        'Referer': refererUrl,
        'Origin': 'https://spse.inaproc.id',
        'Cookie': cookies.toString(),
      }, body);
      cookies.update(res.headers['set-cookie']);

      if (res.status !== 200) { console.log(`HTTP ${res.status}`); break; }

      const json = JSON.parse(res.body);
      const rows = json.data || [];
      console.log(`${rows.length} rows`);

      if (rows.length === 0) { hasMore = false; }
      else {
        allData.push(...rows);
        start += rows.length;
        draw++;
        if (rows.length < PAGE_SIZE) hasMore = false;
        await delay(DELAY_MS);
      }
    } catch (err) {
      console.log(`ERROR: ${err.message}`);
      await delay(5000);
      try {
        const res = await doRequest(apiUrl, 'POST', {
          'User-Agent': UA, 'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
          'X-Requested-With': 'XMLHttpRequest', 'Referer': refererUrl, 'Origin': 'https://spse.inaproc.id', 'Cookie': cookies.toString(),
        }, body);
        cookies.update(res.headers['set-cookie']);
        const rows = (JSON.parse(res.body)).data || [];
        console.log(`    retry → ${rows.length} rows`);
        if (rows.length === 0) hasMore = false;
        else { allData.push(...rows); start += rows.length; draw++; if (rows.length < PAGE_SIZE) hasMore = false; }
      } catch (e) { console.log(`    retry failed`); hasMore = false; }
    }
  }
  console.log(`  Total: ${allData.length} rows`);
  return allData;
}

// ============================================================
// Generic HTML page downloader
// ============================================================
async function downloadPages(packages, getUrlFn, outputDir, cookies, label) {
  fs.mkdirSync(outputDir, { recursive: true });
  let ok = 0, fail = 0, skip = 0;

  console.log(`\n  ${label}: ${packages.length} paket`);
  for (let i = 0; i < packages.length; i++) {
    const id = packages[i].kode;
    const nama = safeName(packages[i].nama);
    const url = getUrlFn(id);
    const filepath = path.join(outputDir, `${id}_${nama}.html`);

    if (fs.existsSync(filepath) && fs.statSync(filepath).size > 200) { skip++; continue; }

    process.stdout.write(`    [${i + 1}/${packages.length}] ${id} ... `);

    try {
      const res = await doRequest(url, 'GET', {
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': `${BASE}/lelang?tahun=2025`,
        'Cookie': cookies.toString(),
      });
      cookies.update(res.headers['set-cookie']);

      if (res.status === 200 && res.body.length > 200) {
        fs.writeFileSync(filepath, res.body, 'utf8');
        ok++;
        console.log('OK');
      } else {
        fail++;
        console.log(`HTTP ${res.status} (${res.body.length}b)`);
      }
    } catch (err) {
      fail++;
      console.log(`FAIL: ${err.code || err.message}`);
    }
    await delay(DELAY_MS);
  }
  console.log(`  → ${ok} ok, ${fail} fail, ${skip} skipped`);
  return { ok, fail, skip };
}

// ============================================================
// Limit helper
// ============================================================
function limit(arr, n) { return n > 0 ? arr.slice(0, n) : arr; }

// ============================================================
// MAIN
// ============================================================
async function main() {
  const ts = Date.now();
  console.log(`=== SPSE Kemkes 2025 — Full Scraper ===`);
  console.log(`Started: ${new Date().toISOString()}`);
  console.log(`Options: limit=${LIMIT || 'ALL'}, skip-json=${SKIP_JSON}, skip-peserta=${SKIP_PESERTA}, skip-pengumuman=${SKIP_PENGUMUMAN}, dry=${DRY_RUN}`);

  // Create all output dirs
  Object.values(DIRS).forEach(d => fs.mkdirSync(d, { recursive: true }));

  // ----------------------------------------------------------------
  // PHASE 1: Scrape JSON (daftar pekerjaan)
  // ----------------------------------------------------------------
  let tenderData = [], nonTenderData = [], pencatatanData = [];

  if (!SKIP_JSON) {
    console.log('\n' + '='.repeat(60));
    console.log('PHASE 1: DAFTAR PEKERJAAN (JSON)');
    console.log('='.repeat(60));

    // --- Tender ---
    console.log('\n1a. Tender 2025');
    const s1 = await initSession(`${BASE}/lelang?tahun=2025`);
    console.log(`  Session OK (token: ${s1.token ? s1.token.substring(0, 12) + '...' : 'NONE'})`);
    const tenderRaw = await fetchAllPages(`${BASE}/dt/lelang?tahun=2025`, `${BASE}/lelang?tahun=2025`, s1.token, s1.cookies, 16);
    tenderData = tenderRaw.map(r => ({ kode: r[0], nama: r[1], instansi: r[2], status: r[3], nilai_pagu: r[4], kualifikasi: r[5], metode_pemilihan: r[6], evaluasi: r[7], jenis_pengadaan: r[8], peserta: r[9], nilai_kontrak: r[10] }));
    fs.writeFileSync(JSON_FILES.tender, JSON.stringify(tenderData, null, 2));
    console.log(`  Saved: ${JSON_FILES.tender} (${tenderData.length} items)`);

    // --- Non Tender ---
    console.log('\n1b. Non Tender 2025');
    const s2 = await initSession(`${BASE}/nontender?tahun=2025`);
    console.log(`  Session OK`);
    const ntRaw = await fetchAllPages(`${BASE}/dt/pl?tahun=2025`, `${BASE}/nontender?tahun=2025`, s2.token, s2.cookies, 12);
    nonTenderData = ntRaw.map(r => ({ kode: r[0], nama: r[1], instansi: r[2], status: r[3], nilai_pagu: r[4], metode: r[5], jenis_pengadaan: r[6], peserta: r[7], nilai_kontrak: r[8] }));
    fs.writeFileSync(JSON_FILES.nonTender, JSON.stringify(nonTenderData, null, 2));
    console.log(`  Saved: ${JSON_FILES.nonTender} (${nonTenderData.length} items)`);

    // --- Pencatatan Non Tender ---
    console.log('\n1c. Pencatatan Non Tender 2025');
    const s3 = await initSession(`${BASE}/pencatatan?tahun=2025`);
    console.log(`  Session OK`);
    const pcRaw = await fetchAllPages(`${BASE}/dt/nonspk?tahun=2025`, `${BASE}/pencatatan?tahun=2025`, s3.token, s3.cookies, 9);
    pencatatanData = pcRaw.map(r => ({ kode: r[0], nama: r[1], instansi: r[2], nilai_pagu: r[3], metode: r[4], jenis_pengadaan: r[5], tahun: r[6], peserta: r[7], status: r[8] }));
    fs.writeFileSync(JSON_FILES.pencatatan, JSON.stringify(pencatatanData, null, 2));
    console.log(`  Saved: ${JSON_FILES.pencatatan} (${pencatatanData.length} items)`);
  } else {
    console.log('\nSkipping JSON (loading from disk)...');
    tenderData     = JSON.parse(fs.readFileSync(JSON_FILES.tender, 'utf8'));
    nonTenderData  = JSON.parse(fs.readFileSync(JSON_FILES.nonTender, 'utf8'));
    pencatatanData = JSON.parse(fs.readFileSync(JSON_FILES.pencatatan, 'utf8'));
    console.log(`  Loaded: ${tenderData.length} tender, ${nonTenderData.length} non-tender, ${pencatatanData.length} pencatatan`);
  }

  // Apply limit for HTML downloads
  const tLimit = limit(tenderData, LIMIT);
  const ntLimit = limit(nonTenderData, LIMIT);
  const pcLimit = limit(pencatatanData, LIMIT);

  if (DRY_RUN) {
    console.log('\n[DRY RUN] Would download:');
    console.log(`  Tender:     ${tLimit.length} paket`);
    console.log(`  Non Tender: ${ntLimit.length} paket`);
    console.log(`  Pencatatan: ${pcLimit.length} paket`);
    return;
  }

  // ----------------------------------------------------------------
  // PHASE 2: Download HTML — Peserta / Pemenang
  // ----------------------------------------------------------------
  if (!SKIP_PESERTA) {
    console.log('\n' + '='.repeat(60));
    console.log('PHASE 2: PESERTA / PEMENANG (HTML)');
    console.log('='.repeat(60));

    const s4 = await initSession(`${BASE}/lelang?tahun=2025`);
    console.log('2a. Tender — Peserta');
    await downloadPages(tLimit, id => `${BASE}/lelang/${id}/peserta`, DIRS.tenderPeserta, s4.cookies, 'Tender Peserta');

    const s5 = await initSession(`${BASE}/nontender?tahun=2025`);
    console.log('2b. Non Tender — Peserta');
    await downloadPages(ntLimit, id => `${BASE}/nontender/${id}/peserta`, DIRS.nonTenderPeserta, s5.cookies, 'Non Tender Peserta');

    const s6 = await initSession(`${BASE}/pencatatan?tahun=2025`);
    console.log('2c. Pencatatan — Pemenang');
    await downloadPages(pcLimit, id => `${BASE}/pencatatan/pengumumannonspkpemenang?id=${id}`, DIRS.pencatatanPemenang, s6.cookies, 'Pencatatan Pemenang');
  }

  // ----------------------------------------------------------------
  // PHASE 3: Download HTML — Pengumuman
  // ----------------------------------------------------------------
  if (!SKIP_PENGUMUMAN) {
    console.log('\n' + '='.repeat(60));
    console.log('PHASE 3: PENGUMUMAN (HTML)');
    console.log('='.repeat(60));

    const s7 = await initSession(`${BASE}/lelang?tahun=2025`);
    console.log('3a. Tender — Pengumuman');
    await downloadPages(tLimit, id => `${BASE}/lelang/${id}/pengumumanlelang`, DIRS.tenderPengumuman, s7.cookies, 'Tender Pengumuman');

    const s8 = await initSession(`${BASE}/nontender?tahun=2025`);
    console.log('3b. Non Tender — Pengumuman');
    await downloadPages(ntLimit, id => `${BASE}/nontender/${id}/pengumumanpl`, DIRS.nonTenderPengumuman, s8.cookies, 'Non Tender Pengumuman');

    const s9 = await initSession(`${BASE}/pencatatan?tahun=2025`);
    console.log('3c. Pencatatan — Pengumuman');
    await downloadPages(pcLimit, id => `${BASE}/pencatatan/pengumumannonspk?id=${id}`, DIRS.pencatatanPengumuman, s9.cookies, 'Pencatatan Pengumuman');
  }

  // ----------------------------------------------------------------
  // Summary
  // ----------------------------------------------------------------
  const elapsed = ((Date.now() - ts) / 1000).toFixed(1);
  console.log('\n' + '='.repeat(60));
  console.log(`DONE in ${elapsed}s`);
  console.log('='.repeat(60));
  console.log(`\nJSON files:`);
  console.log(`  tender_2025.json:                 ${tenderData.length} items`);
  console.log(`  non_tender_2025.json:             ${nonTenderData.length} items`);
  console.log(`  pencatatan_non_tender_2025.json:  ${pencatatanData.length} items`);
  console.log(`\nHTML directories (under output/html/):`);
  console.log(`  tender/peserta/          non_tender/peserta/        pencatatan/pemenang/`);
  console.log(`  tender/pengumuman/       non_tender/pengumuman/     pencatatan/pengumuman/`);
}

main().catch(console.error);
