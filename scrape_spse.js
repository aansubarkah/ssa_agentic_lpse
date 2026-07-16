const fs = require('fs');
const path = require('path');
const https = require('https');
const { gunzipSync, inflateSync, brotliDecompressSync } = require('zlib');

// ============================================================
// Configuration
// ============================================================
const BASE = 'https://spse.inaproc.id/kemkes';
const OUTPUT_DIR = path.join(__dirname, 'output');
const DELAY_MS = 600;
const PAGE_SIZE = 300;

const HTML_DIR = {
  tender: path.join(OUTPUT_DIR, 'html', 'tender', 'peserta'),
  nonTender: path.join(OUTPUT_DIR, 'html', 'non_tender', 'peserta'),
  pencatatan: path.join(OUTPUT_DIR, 'html', 'pencatatan', 'pemenang'),
};

// ============================================================
// HTTP helpers
// ============================================================
function doRequest(url, method, headers, body) {
  return new Promise((resolve, reject) => {
    const u = new URL(url);
    const opts = {
      hostname: u.hostname,
      path: u.pathname + u.search,
      method: method || 'GET',
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

// Cookie jar that merges set-cookie from responses
class CookieJar {
  constructor() { this.jar = {}; }
  update(setCookieHeaders) {
    for (const sc of (setCookieHeaders || [])) {
      const [nameVal, ...attrs] = sc.split(';').map(s => s.trim());
      const idx = nameVal.indexOf('=');
      const name = nameVal.substring(0, idx).trim();
      const value = nameVal.substring(idx + 1);
      if (attrs.some(a => a.startsWith('Max-Age=0'))) delete this.jar[name];
      else if (value) this.jar[name] = value;
    }
  }
  toString() { return Object.entries(this.jar).map(([k, v]) => `${k}=${v}`).join('; '); }
}

const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0';

function initSession(pageUrl) {
  // GET the main page, return { cookies, token }
  return new Promise((resolve, reject) => {
    const u = new URL(pageUrl);
    const req = https.request({
      hostname: u.hostname,
      path: u.pathname + u.search,
      method: 'GET',
      headers: {
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Host': u.hostname,
      },
    }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        const loc = res.headers.location;
        return initSession(loc.startsWith('http') ? loc : `https://${u.hostname}${loc}`).then(resolve).catch(reject);
      }
      const chunks = [];
      const enc = res.headers['content-encoding'];
      res.on('data', (c) => chunks.push(c));
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
    });
    req.on('error', reject);
    req.end();
  });
}

function delay(ms) { return new Promise(r => setTimeout(r, ms)); }

// ============================================================
// DataTables POST
// ============================================================
function buildDtParams(token, draw, start, length, numCols) {
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
  console.log(`  Fetching: ${apiUrl}`);
  const allData = [];
  let draw = 1, start = 0, hasMore = true;

  while (hasMore) {
    const body = buildDtParams(token, draw, start, PAGE_SIZE, numCols);
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

      if (res.status !== 200) {
        console.log(`HTTP ${res.status}`);
        // Might need to re-init session
        break;
      }

      const json = JSON.parse(res.body);
      const rows = json.data || [];
      console.log(`${rows.length} rows`);

      if (rows.length === 0) {
        hasMore = false;
      } else {
        allData.push(...rows);
        start += rows.length;
        draw++;
        if (rows.length < PAGE_SIZE) hasMore = false;
        await delay(DELAY_MS);
      }
    } catch (err) {
      console.log(`ERROR: ${err.message}`);
      await delay(5000);
      // Retry once
      try {
        const res = await doRequest(apiUrl, 'POST', {
          'User-Agent': UA,
          'Accept': 'application/json, text/javascript, */*; q=0.01',
          'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
          'X-Requested-With': 'XMLHttpRequest',
          'Referer': refererUrl,
          'Origin': 'https://spse.inaproc.id',
          'Cookie': cookies.toString(),
        }, body);
        cookies.update(res.headers['set-cookie']);
        const json = JSON.parse(res.body);
        const rows = json.data || [];
        console.log(`    retry → ${rows.length} rows`);
        if (rows.length === 0) { hasMore = false; }
        else {
          allData.push(...rows);
          start += rows.length;
          draw++;
          if (rows.length < PAGE_SIZE) hasMore = false;
        }
      } catch (err2) {
        console.log(`    retry failed: ${err2.message}`);
        hasMore = false;
      }
    }
  }

  console.log(`  Total: ${allData.length} rows`);
  return allData;
}

// ============================================================
// Download HTML pages
// ============================================================
async function downloadHtmlPages(packages, getUrlFn, outputDir, cookies) {
  fs.mkdirSync(outputDir, { recursive: true });
  let ok = 0, fail = 0, skip = 0;

  for (let i = 0; i < packages.length; i++) {
    const pkg = packages[i];
    const id = pkg.kode;
    const url = getUrlFn(id);
    const safeName = pkg.nama.replace(/[\/\\:*?"<>|\n\r]/g, '-').substring(0, 80);
    const filepath = path.join(outputDir, `${id}_${safeName}.html`);

    if (fs.existsSync(filepath) && fs.statSync(filepath).size > 100) {
      skip++;
      continue;
    }

    process.stdout.write(`  [${i + 1}/${packages.length}] ${id} ... `);

    try {
      const res = await doRequest(url, 'GET', {
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': `${BASE}/lelang?tahun=2025`,
        'Cookie': cookies.toString(),
      });
      cookies.update(res.headers['set-cookie']);

      if (res.status === 200 && res.body.length > 100) {
        fs.writeFileSync(filepath, res.body, 'utf8');
        ok++;
        console.log('OK');
      } else {
        fail++;
        console.log(`HTTP ${res.status} (${res.body.length} bytes)`);
      }
    } catch (err) {
      fail++;
      console.log(`FAIL: ${err.message}`);
    }

    await delay(DELAY_MS);
  }

  console.log(`  Done: ${ok} saved, ${fail} failed, ${skip} skipped (existing)`);
  return { ok, fail, skip };
}

// ============================================================
// MAIN
// ============================================================
async function main() {
  const ts = Date.now();
  console.log(`START: ${new Date().toISOString()}`);

  Object.values(HTML_DIR).forEach(d => fs.mkdirSync(d, { recursive: true }));

  // ============================================================
  // 1. TENDER 2025
  // ============================================================
  console.log('\n' + '='.repeat(60));
  console.log('1. TENDER 2025');
  console.log('='.repeat(60));

  const tenderPageUrl = `${BASE}/lelang?tahun=2025`;
  const tenderApiUrl = `${BASE}/dt/lelang?tahun=2025`;

  const s1 = await initSession(tenderPageUrl);
  console.log(`  Session OK, token: ${s1.token ? s1.token.substring(0, 12) + '...' : 'NONE'}`);

  const tenderRaw = await fetchAllPages(tenderApiUrl, tenderPageUrl, s1.token, s1.cookies, 16);

  const tenderData = tenderRaw.map(r => ({
    kode: r[0],
    nama: r[1],
    instansi: r[2],
    status: r[3],
    nilai_pagu: r[4],
    kualifikasi: r[5],
    metode_pemilihan: r[6],
    evaluasi: r[7],
    jenis_pengadaan: r[8],
    peserta: r[9],
    nilai_kontrak: r[10],
  }));

  fs.writeFileSync(path.join(OUTPUT_DIR, 'tender_2025.json'), JSON.stringify(tenderData, null, 2));
  console.log(`  JSON saved: ${tenderData.length} items`);

  // ============================================================
  // 2. NON TENDER 2025
  // ============================================================
  console.log('\n' + '='.repeat(60));
  console.log('2. NON TENDER 2025');
  console.log('='.repeat(60));

  const ntPageUrl = `${BASE}/nontender?tahun=2025`;
  const ntApiUrl = `${BASE}/dt/pl?tahun=2025`;

  const s2 = await initSession(ntPageUrl);
  console.log(`  Session OK, token: ${s2.token ? s2.token.substring(0, 12) + '...' : 'NONE'}`);

  const ntRaw = await fetchAllPages(ntApiUrl, ntPageUrl, s2.token, s2.cookies, 12);

  const ntData = ntRaw.map(r => ({
    kode: r[0],
    nama: r[1],
    instansi: r[2],
    status: r[3],
    nilai_pagu: r[4],
    metode: r[5],
    jenis_pengadaan: r[6],
    peserta: r[7],
    nilai_kontrak: r[8],
  }));

  fs.writeFileSync(path.join(OUTPUT_DIR, 'non_tender_2025.json'), JSON.stringify(ntData, null, 2));
  console.log(`  JSON saved: ${ntData.length} items`);

  // ============================================================
  // 3. PENCATATAN NON TENDER 2025
  // ============================================================
  console.log('\n' + '='.repeat(60));
  console.log('3. PENCATATAN NON TENDER 2025');
  console.log('='.repeat(60));

  const pcPageUrl = `${BASE}/pencatatan?tahun=2025`;
  const pcApiUrl = `${BASE}/dt/nonspk?tahun=2025`;

  const s3 = await initSession(pcPageUrl);
  console.log(`  Session OK, token: ${s3.token ? s3.token.substring(0, 12) + '...' : 'NONE'}`);

  const pcRaw = await fetchAllPages(pcApiUrl, pcPageUrl, s3.token, s3.cookies, 9);

  const pcData = pcRaw.map(r => ({
    kode: r[0],
    nama: r[1],
    instansi: r[2],
    nilai_pagu: r[3],
    metode: r[4],
    jenis_pengadaan: r[5],
    tahun: r[6],
    peserta: r[7],
    status: r[8],
  }));

  fs.writeFileSync(path.join(OUTPUT_DIR, 'pencatatan_non_tender_2025.json'), JSON.stringify(pcData, null, 2));
  console.log(`  JSON saved: ${pcData.length} items`);

  // ============================================================
  // 4. HTML - TENDER PESERTA/PEMENANG
  // ============================================================
  console.log('\n' + '='.repeat(60));
  console.log('4a. HTML - TENDER PESERTA');
  console.log('='.repeat(60));

  // Re-init session for HTML scraping
  const s4 = await initSession(tenderPageUrl);
  await downloadHtmlPages(
    tenderData,
    (id) => `${BASE}/lelang/${id}/peserta`,
    HTML_DIR.tender,
    s4.cookies
  );

  // ============================================================
  // 4b. HTML - NON TENDER PESERTA
  // ============================================================
  console.log('\n' + '='.repeat(60));
  console.log('4b. HTML - NON TENDER PESERTA');
  console.log('='.repeat(60));

  const s5 = await initSession(ntPageUrl);
  await downloadHtmlPages(
    ntData,
    (id) => `${BASE}/nontender/${id}/peserta`,
    HTML_DIR.nonTender,
    s5.cookies
  );

  // ============================================================
  // 4c. HTML - PENCATATAN PEMENANG
  // ============================================================
  console.log('\n' + '='.repeat(60));
  console.log('4c. HTML - PENCATATAN PEMENANG');
  console.log('='.repeat(60));

  const s6 = await initSession(pcPageUrl);
  await downloadHtmlPages(
    pcData,
    (id) => `${BASE}/pencatatan/pengumumannonspkpemenang?id=${id}`,
    HTML_DIR.pencatatan,
    s6.cookies
  );

  // ============================================================
  // Summary
  // ============================================================
  const elapsed = ((Date.now() - ts) / 1000).toFixed(1);
  console.log('\n' + '='.repeat(60));
  console.log(`DONE in ${elapsed}s`);
  console.log('='.repeat(60));
  console.log(`  tender_2025.json:                 ${tenderData.length} items`);
  console.log(`  non_tender_2025.json:             ${ntData.length} items`);
  console.log(`  pencatatan_non_tender_2025.json:  ${pcData.length} items`);
  console.log(`  HTML files in: output/html/`);
  console.log(`    tender/peserta/`);
  console.log(`    non_tender/peserta/`);
  console.log(`    pencatatan/pemenang/`);
}

main().catch(console.error);
