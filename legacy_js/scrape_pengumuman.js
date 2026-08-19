const fs = require('fs');
const path = require('path');
const https = require('https');
const { gunzipSync, inflateSync, brotliDecompressSync } = require('zlib');

// ============================================================
// Config
// ============================================================
const BASE = 'https://spse.inaproc.id/kemkes';
const OUTPUT_DIR = path.join(__dirname, 'output', 'html');
const DELAY_MS = 600;

const DIRS = {
  tender:     path.join(OUTPUT_DIR, 'tender', 'pengumuman'),
  nonTender:  path.join(OUTPUT_DIR, 'non_tender', 'pengumuman'),
  pencatatan: path.join(OUTPUT_DIR, 'pencatatan', 'pengumuman'),
};

// ============================================================
// HTTP helpers
// ============================================================
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0';

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

function initSession(pageUrl) {
  return new Promise((resolve, reject) => {
    const u = new URL(pageUrl);
    const req = https.request({
      hostname: u.hostname,
      path: u.pathname + u.search,
      method: 'GET',
      headers: { 'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8', 'Host': u.hostname },
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
// Sanitize filename (handle tabs, newlines, colons etc.)
// ============================================================
function safeName(raw) {
  return raw
    .replace(/<[^>]+>/g, '')              // strip HTML tags
    .replace(/[\t\n\r]/g, ' ')             // whitespace → space
    .replace(/[\/\\:*?"<>|\0]/g, '-')      // illegal chars
    .replace(/\s+/g, ' ')
    .trim()
    .substring(0, 80);
}

// ============================================================
// Download pengumuman HTML for a list of packages
// ============================================================
async function downloadPengumuman(packages, getUrlFn, outputDir, cookies, label) {
  fs.mkdirSync(outputDir, { recursive: true });
  let ok = 0, fail = 0, skip = 0;

  console.log(`\n  ${label}: ${packages.length} paket`);
  for (let i = 0; i < packages.length; i++) {
    const id = packages[i].kode;
    const nama = safeName(packages[i].nama || '');
    const url = getUrlFn(id);
    const filepath = path.join(outputDir, `${id}_${nama}.html`);

    // Skip if already exists and non-trivial
    if (fs.existsSync(filepath) && fs.statSync(filepath).size > 200) {
      skip++;
      continue;
    }

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
        console.log(`HTTP ${res.status} (${res.body.length} bytes)`);
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
// MAIN
// ============================================================
async function main() {
  const ts = Date.now();
  console.log(`START: ${new Date().toISOString()}`);

  Object.values(DIRS).forEach(d => fs.mkdirSync(d, { recursive: true }));

  // Load previously scraped JSON data
  const tenderData     = JSON.parse(fs.readFileSync(path.join(__dirname, 'output', 'tender_2025.json'), 'utf8'));
  const nonTenderData  = JSON.parse(fs.readFileSync(path.join(__dirname, 'output', 'non_tender_2025.json'), 'utf8'));
  const pencatatanData = JSON.parse(fs.readFileSync(path.join(__dirname, 'output', 'pencatatan_non_tender_2025.json'), 'utf8'));

  console.log(`Loaded: ${tenderData.length} tender, ${nonTenderData.length} non-tender, ${pencatatanData.length} pencatatan`);

  // ============================================================
  // 1. TENDER PENGUMUMAN
  // ============================================================
  console.log('\n' + '='.repeat(60));
  console.log('1. TENDER - PENGUMUMAN');
  console.log('='.repeat(60));

  const s1 = await initSession(`${BASE}/lelang?tahun=2025`);
  console.log(`  Session OK, token: ${s1.token ? s1.token.substring(0, 12) + '...' : 'NONE'}`);

  const r1 = await downloadPengumuman(
    tenderData,
    (id) => `${BASE}/lelang/${id}/pengumumanlelang`,
    DIRS.tender,
    s1.cookies,
    'Pengumuman Tender'
  );

  // ============================================================
  // 2. NON TENDER PENGUMUMAN
  // ============================================================
  console.log('\n' + '='.repeat(60));
  console.log('2. NON TENDER - PENGUMUMAN');
  console.log('='.repeat(60));

  const s2 = await initSession(`${BASE}/nontender?tahun=2025`);
  console.log(`  Session OK, token: ${s2.token ? s2.token.substring(0, 12) + '...' : 'NONE'}`);

  const r2 = await downloadPengumuman(
    nonTenderData,
    (id) => `${BASE}/nontender/${id}/pengumumanpl`,
    DIRS.nonTender,
    s2.cookies,
    'Pengumuman Non Tender'
  );

  // ============================================================
  // 3. PENCATATAN NON TENDER PENGUMUMAN
  // ============================================================
  console.log('\n' + '='.repeat(60));
  console.log('3. PENCATATAN - PENGUMUMAN');
  console.log('='.repeat(60));

  const s3 = await initSession(`${BASE}/pencatatan?tahun=2025`);
  console.log(`  Session OK, token: ${s3.token ? s3.token.substring(0, 12) + '...' : 'NONE'}`);

  const r3 = await downloadPengumuman(
    pencatatanData,
    (id) => `${BASE}/pencatatan/pengumumannonspk?id=${id}`,
    DIRS.pencatatan,
    s3.cookies,
    'Pengumuman Pencatatan'
  );

  // ============================================================
  // Summary
  // ============================================================
  const elapsed = ((Date.now() - ts) / 1000).toFixed(1);
  const totalOk = r1.ok + r2.ok + r3.ok;
  const totalFail = r1.fail + r2.fail + r3.fail;
  console.log('\n' + '='.repeat(60));
  console.log(`DONE in ${elapsed}s`);
  console.log('='.repeat(60));
  console.log(`  Tender pengumuman:     ${r1.ok} ok, ${r1.fail} fail, ${r1.skip} skip`);
  console.log(`  Non tender pengumuman: ${r2.ok} ok, ${r2.fail} fail, ${r2.skip} skip`);
  console.log(`  Pencatatan pengumuman: ${r3.ok} ok, ${r3.fail} fail, ${r3.skip} skip`);
  console.log(`  TOTAL: ${totalOk} ok, ${totalFail} fail`);
  console.log(`  HTML dirs:`);
  console.log(`    output/html/tender/pengumuman/`);
  console.log(`    output/html/non_tender/pengumuman/`);
  console.log(`    output/html/pencatatan/pengumuman/`);
}

main().catch(console.error);
