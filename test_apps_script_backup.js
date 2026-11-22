const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');
const vm = require('node:vm');

const now = new Date('2026-11-17T21:00:00Z'); // Apps Script uses a KST-shifted Date.
const quote = {
  itemCode: 'KOSPI', closePrice: '4,968.48', marketStatus: 'CLOSE',
  localTradedAt: '2026-11-17T20:15:00+09:00', stockExchangeType: {zoneId: 'Asia/Seoul'},
};
const sources = ['politics', 'economic', 'society', 'foreign'];

function loadScript() {
  const gas = vm.createContext({});
  vm.runInContext(fs.readFileSync('AppsScript_Code.gs', 'utf8'), gas);
  gas.nowKST_ = () => now;
  gas.fetchText_ = url => {
    if (url.includes('m.stock.naver')) throw new Error('primary unavailable');
    if (url.includes('polling.finance')) return JSON.stringify({datas: [quote]});
    const slug = url.split('/').at(-1);
    const group = sources.indexOf(slug);
    if (group < 0) throw new Error('source unavailable');
    return Array.from({length: 5}, (_, index) => {
      const id = '2026111712380' + group + '00' + index;
      return '<a href="https://v.daum.net/v/' + id + '"><strong>검증용 기사 제목을 포함하는 원문</strong></a>';
    }).join('');
  };
  return gas;
}

function page(gas, shortnews = '이전 기사', weather = '이전 예보') {
  let html = '<div id="auth-gate"></div>' + Array.from({length: 30},
    (_, index) => '<section class="card" data-slot="' + (index + 1) + '"></section>').join('');
  for (const [key, body] of Object.entries({shortnews, weather, transactions: '19번 보존'})) {
    html += '<textarea id="ta-' + key + '">' + gas.escapeHtml_(body) + '</textarea>';
    html += 'window.__content_' + key + ' = ' + JSON.stringify(body) + ';';
  }
  return html + '<div id="preview-shortnews">이전 기사</div>';
}

function isolateBackup(gas, files) {
  let result;
  gas.ghConfig_ = () => ({});
  gas.Logger = {log() {}};
  gas.ghRequest_ = (cfg, endpoint) => {
    assert.equal(endpoint, '/git/ref/heads/main');
    return {object: {sha: 'starting-main'}};
  };
  gas.ghGetTextFile_ = (path, ref) => {
    assert.equal(ref, 'starting-main');
    return files[path] ?? null;
  };
  gas.commitBackup_ = (cfg, base, changes) => {
    assert.equal(base, 'starting-main');
    result = changes;
  };
  gas.fetchMarket_ = () => ({});
  for (const key of ['Fortune', 'RealestateNews', 'WorldNews', 'FinanceNews', 'AiNews']) {
    gas['fetch' + key + '_'] = () => undefined;
  }
  return () => result;
}

test('backup uses observed links and dated KOSPI, and preserves the other slots and copy data', () => {
  const gas = loadScript();
  const quick = gas.fetchShortnews_(now);
  assert.equal(gas.quicknewsQuality_(quick, now), 15);
  assert.match(quick, /4,968.48pt \(2026-11-17 종가 · 네이버 표시 20:15 KST\)/);
  gas.fetchWeather_ = () => ({ok: false});
  const result = isolateBackup(gas, {'briefing.html': page(gas)});
  gas.runBackupNow();
  const changes = result();
  assert.equal(changes['shortnews-tue.txt'], quick);
  const html = changes['briefing.html'];
  assert.equal(gas.readCardBody_(html, 'shortnews'), quick.trim());
  assert.ok(html.includes('window.__content_shortnews = ' + JSON.stringify(quick.trim())));
  assert.equal((html.match(/class="news-source-link"/g) || []).length, 15);
  assert.equal(gas.readCardBody_(html, 'transactions'), '19번 보존');
  assert.equal((html.match(/<section class="card"/g) || []).length, 30);
});

test('complete primary quicknews wins and same-day weather stops later collection', () => {
  const gas = loadScript();
  const primary = gas.fetchShortnews_(now).replace('검증용 기사 제목을 포함하는 원문', '검증된 기존 요약입니다.');
  const weather = '2026년 11월 17일 화요일\n\n❒ 지역별 날씨전망 ❒\n\n' +
    gas.CITIES.map(city => '✫' + city[0] + '(☀️)➠(☀️)  7℃ ~ 15℃').join('\n');
  const files = {
    'briefing.html': page(gas, primary.trim(), weather),
    'shortnews-tue.txt': primary, 'shortnews.txt': primary,
    'weather-2026-11-17.txt': weather,
    'weather-status.txt': JSON.stringify({status: 'failed', failedAtKst: '2026-11-17T20:54:00+09:00'}),
  };
  const result = isolateBackup(gas, files);
  gas.fetchWeather_ = gas.fetchShortnews_ = () => assert.fail('unexpected re-collection');
  gas.runBackupNow();
  const changes = result();
  assert.equal(changes['shortnews-tue.txt'], undefined);
  assert.equal(changes['weather-2026-11-17.txt'], undefined);
  assert.equal(gas.readCardBody_(changes['briefing.html'] || files['briefing.html'], 'weather'), weather);
});

test('unverified fallback cannot replace the existing article body', () => {
  const gas = loadScript();
  const read = gas.fetchText_;
  gas.fetchText_ = url => url.includes('polling.finance') ?
    JSON.stringify({datas: [{...quote, localTradedAt: '2026-11-18T20:15:00+09:00'}]}) : read(url);
  assert.equal(gas.fetchShortnews_(now), '');
  gas.fetchWeather_ = () => ({ok: false});
  const result = isolateBackup(gas, {'briefing.html': page(gas)});
  gas.runBackupNow();
  assert.equal(result()['shortnews.txt'], undefined);
  assert.equal(gas.readCardBody_(result()['briefing.html'], 'shortnews'), '이전 기사');
});

test('backup publishes a single non-forced commit from its verified main revision', () => {
  const gas = loadScript();
  const seen = [];
  gas.ghRequest_ = (cfg, endpoint, method, payload) => {
    seen.push({endpoint, method, payload});
    if (endpoint === '/git/commits/base') return {tree: {sha: 'base-tree'}};
    if (endpoint === '/git/trees') return {sha: 'new-tree'};
    if (endpoint === '/git/commits') return {sha: 'new-commit'};
    throw new Error('main advanced');
  };
  assert.throws(() => gas.commitBackup_({}, 'base', {'briefing.html': 'page', 'shortnews.txt': 'news'}, '2026-11-17'), /main advanced/);
  assert.equal(seen.length, 4);
  assert.equal(seen[1].payload.base_tree, 'base-tree');
  assert.equal(seen[1].payload.tree.length, 2);
  assert.equal(seen[3].payload.force, false);
});

test('valid same-day aliases also prevent another request after cooldown expires', () => {
  const gas = loadScript();
  const weather = '2026년 11월 17일 화요일\n\n❒ 지역별 날씨전망 ❒\n\n' +
    gas.CITIES.map(city => '✫' + city[0] + '(☀️)➠(☀️)  7℃ ~ 15℃').join('\n');
  const files = {
    'briefing.html': page(gas),
    'weather-tue.txt': weather,
    'weather-status.txt': JSON.stringify({status: 'failed', failedAtKst: '2026-11-17T12:00:00+09:00'}),
  };
  const result = isolateBackup(gas, files);
  gas.fetchWeather_ = () => assert.fail('same-day forecast already collected');
  gas.runBackupNow();
  assert.equal(gas.readCardBody_(result()['briefing.html'], 'weather'), weather);
  assert.equal(result()['weather-status.txt'], undefined);
});

test('previous-day and partial weather allow collection and retain a failure state', () => {
  const gas = loadScript();
  const files = {'briefing.html': page(gas), 'weather.txt': '2026년 11월 16일 월요일\n이전 예보'};
  const result = isolateBackup(gas, files);
  let attempts = 0;
  gas.fetchWeather_ = () => { attempts++; return {ok:false}; };
  gas.runBackupNow();
  assert.equal(attempts, 1);
  assert.equal(JSON.parse(result()['weather-status.txt']).status, 'failed');
  assert.match(gas.readCardBody_(result()['briefing.html'], 'weather'), /당일 날씨 자료를 확보하지 못했습니다/);
});
