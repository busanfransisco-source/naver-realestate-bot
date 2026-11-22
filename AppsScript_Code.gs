/**
 * ============================================================
 *  naver-realestate-bot 백업 파이프라인 (Google Apps Script)
 * ============================================================
 * GitHub Actions가 장애로 멈춰있을 때를 대비한 완전 독립 실행 경로.
 * 구글 서버에서 돌아가므로 GitHub 인프라와 분리되어 있음.
 *
 * 동작 방식:
 *  1) runBackupIfNeeded() 가 트리거로 매일 몇 차례 실행됨
 *  2) 먼저 GitHub의 last-refresh.txt 시간을 확인해서
 *     "GitHub Actions가 이미 오늘자로 갱신했는지" 체크
 *  3) 이미 최신이면 아무 것도 안 하고 바로 종료 (중복 방지, 할당량 절약)
 *  4) 오래됐으면 검증된 보완 자료를 기존 브리핑 카드와 원자료에 함께 반영
 *
 * 사용 전 설정 (Apps Script 편집기 > 프로젝트 설정 > 스크립트 속성):
 *   GITHUB_TOKEN   : GitHub Personal Access Token (본인이 직접 입력)
 *   REPO_OWNER     : busanfransisco-source
 *   REPO_NAME      : naver-realestate-bot
 *   RONE_KEY       : (선택) 국토부 R-ONE API 키. 없으면 시세동향 섹션만 스킵됨
 *
 * 트리거 설정: setupTriggers() 를 한 번 실행하면 자동으로 매일 여러 번 예약됨.
 * ============================================================
 */

// ---------------------------------------------------------------
// 공통 상수
// ---------------------------------------------------------------

var WEEKDAY_EN = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
var WEEKDAY_KR = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"];

var UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

function nowKST_() {
  var utc = new Date();
  return new Date(utc.getTime() + 9 * 60 * 60 * 1000);
}

function weekdayIdx_(d) {
  var jsDay = d.getUTCDay();
  return (jsDay + 6) % 7;
}

function pad2_(n) { return (n < 10 ? "0" : "") + n; }

function dateStamp_(d) {
  return d.getUTCFullYear() + "-" + pad2_(d.getUTCMonth() + 1) + "-" + pad2_(d.getUTCDate());
}

function fetchText_(url, options) {
  var opt = options || {};
  opt.headers = opt.headers || {};
  if (!opt.headers["User-Agent"]) opt.headers["User-Agent"] = UA;
  opt.muteHttpExceptions = true;
  var resp = UrlFetchApp.fetch(url, opt);
  return resp.getContentText("UTF-8");
}

// 수집 실패 문구가 브리핑이나 카카오톡으로 나가는 것을 막는다.
function hasFetchFailure_(content) {
  return !content || /가져오기 실패|가져오지 못했습니다|파일을 찾을 수 없습니다/.test(content);
}

function htmlUnescape_(s) {
  if (!s) return s;
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, " ");
}

function stripTags_(html) {
  return htmlUnescape_(html.replace(/<[^>]*>/g, "")).replace(/\s+/g, " ").trim();
}

function fetchNaverSectionArticles_(url, maxArticles) {
  var html;
  try {
    html = fetchText_(url);
  } catch (e) {
    return [];
  }
  var articles = [];
  var seen = {};
  var re1 = /<a\b(?=[^>]*\bclass="[^"]*(?:sa_text_title|cluster_text_headline)[^"]*")(?=[^>]*\bhref="([^"]*)")[^>]*>([\s\S]*?)<\/a>/g;
  var m;
  while ((m = re1.exec(html)) !== null && articles.length < maxArticles) {
    var href = m[1];
    var title = stripTags_(m[2]);
    if (!title || seen[href]) continue;
    if (href.indexOf("/") === 0) href = "https://news.naver.com" + href;
    seen[href] = true;
    articles.push({ title: title, url: href });
  }
  if (articles.length === 0) {
    var re2 = /<a[^>]+href="([^"]*\/article\/[^"]*)"[^>]*>([\s\S]*?)<\/a>/g;
    while ((m = re2.exec(html)) !== null && articles.length < maxArticles) {
      var href2 = m[1];
      var title2 = stripTags_(m[2]);
      if (!title2 || seen[href2]) continue;
      if (href2.indexOf("/") === 0) href2 = "https://news.naver.com" + href2;
      seen[href2] = true;
      articles.push({ title: title2, url: href2 });
    }
  }
  return articles;
}

function buildArticleListReport_(headline, articles) {
  var lines = [headline, ""];
  articles.forEach(function (a) {
    lines.push(a.title);
    lines.push(a.url);
    lines.push("");
  });
  return lines.join("\n").replace(/\n+$/, "") + "\n";
}

function fetchWorldNews_(now) {
  var urls = ["https://news.naver.com/section/104", "https://news.naver.com/breakingnews/section/104"];
  var articles = [];
  for (var i = 0; i < urls.length; i++) {
    articles = fetchNaverSectionArticles_(urls[i], 10);
    if (articles.length) break;
  }
  var weekday = WEEKDAY_KR[weekdayIdx_(now)];
  var headline = "🌏 " + (now.getUTCFullYear() % 100) + "년 " + (now.getUTCMonth() + 1) + "월 " + now.getUTCDate() + "일 " + weekday + " 세계 뉴스";
  return { prefix: "world", content: buildArticleListReport_(headline, articles), ok: articles.length > 0 };
}

function fetchFinanceNews_(now) {
  var articles = fetchNaverSectionArticles_("https://news.naver.com/breakingnews/section/101/259", 10);
  var weekday = WEEKDAY_KR[weekdayIdx_(now)];
  var headline = "🏦 " + (now.getUTCFullYear() % 100) + "년 " + (now.getUTCMonth() + 1) + "월 " + now.getUTCDate() + "일 " + weekday + " 금융 뉴스";
  return { prefix: "finance", content: buildArticleListReport_(headline, articles), ok: articles.length > 0 };
}

function fetchRealestateNews_(now) {
  var articles = fetchNaverSectionArticles_("https://news.naver.com/breakingnews/section/101/260", 10);
  var weekday = WEEKDAY_KR[weekdayIdx_(now)];
  var headline = (now.getUTCFullYear() % 100) + "년 " + (now.getUTCMonth() + 1) + "월 " + now.getUTCDate() + "일 " + weekday + " 부동산 주요뉴스";
  return { prefix: "realestate", content: buildArticleListReport_(headline, articles), ok: articles.length > 0 };
}

function fetchAiNews_(now) {
  var url = "https://www.aitimes.com/news/articleList.html?box_idxno=10&view_type=sm";
  var html;
  try { html = fetchText_(url); } catch (e) { html = ""; }
  var articles = [];
  var seen = {};
  var re = /<a[^>]+href="([^"]*\/news\/articleView\.html\?idxno=\d+[^"]*)"[^>]*>([\s\S]*?)<\/a>/g;
  var m;
  while ((m = re.exec(html)) !== null && articles.length < 10) {
    var href = m[1];
    if (href.indexOf("/") === 0) href = "https://www.aitimes.com" + href;
    var title = stripTags_(m[2]);
    if (!title || title.length < 5 || seen[href]) continue;
    seen[href] = true;
    articles.push({ title: title, url: href });
  }
  var weekday = WEEKDAY_KR[weekdayIdx_(now)];
  var headline = "🤖 " + (now.getUTCFullYear() % 100) + "년 " + (now.getUTCMonth() + 1) + "월 " + now.getUTCDate() + "일 " + weekday + " AI 뉴스";
  return { prefix: "ai", content: buildArticleListReport_(headline, articles), ok: articles.length > 0 };
}

var CITIES = [
  ["서울", 37.5665, 126.9780], ["인천", 37.4563, 126.7052], ["수원", 37.2636, 127.0286],
  ["춘천", 37.8813, 127.7298], ["강릉", 37.7519, 128.8761], ["청주", 36.6424, 127.4890],
  ["대전", 36.3504, 127.3845], ["세종", 36.4801, 127.2891], ["전주", 35.8242, 127.1480],
  ["광주", 35.1595, 126.8526], ["대구", 35.8714, 128.6014], ["부산", 35.1796, 129.0756],
  ["울산", 35.5384, 129.3114], ["창원", 35.2281, 128.6811], ["제주", 33.4996, 126.5312]
];

function codeToEmoji_(code) {
  if (code === 0) return "☀️";
  if (code === 1) return "🌤️";
  if (code === 2) return "⛅";
  if (code === 3) return "☁️";
  if (code === 45 || code === 48) return "🌫️";
  if ([51, 53, 55, 56, 57].indexOf(code) !== -1) return "🌦️";
  if ([61, 63, 65, 66, 67, 80, 81, 82].indexOf(code) !== -1) return "🌧️";
  if ([71, 73, 75, 77, 85, 86].indexOf(code) !== -1) return "❄️";
  if ([95, 96, 99].indexOf(code) !== -1) return "⛈️";
  return "☁️";
}

function mostCommon_(arr) {
  var counts = {};
  var best = null, bestN = -1;
  arr.forEach(function (v) {
    counts[v] = (counts[v] || 0) + 1;
    if (counts[v] > bestN) { bestN = counts[v]; best = v; }
  });
  return best === null ? 3 : best;
}

function fetchWeather_(now) {
  var weekday = WEEKDAY_KR[weekdayIdx_(now)];
  var dateLine = now.getUTCFullYear() + "년 " + (now.getUTCMonth() + 1) + "월 " + now.getUTCDate() + "일 " + weekday;
  var lines = [dateLine, "", "❒ 지역별 날씨전망 ❒", ""];

  var lats = CITIES.map(function (c) { return c[1]; }).join(",");
  var lons = CITIES.map(function (c) { return c[2]; }).join(",");
  var url = "https://api.open-meteo.com/v1/forecast?latitude=" + lats + "&longitude=" + lons +
    "&hourly=weather_code&daily=temperature_2m_max,temperature_2m_min&timezone=Asia%2FSeoul&forecast_days=1";

  var data;
  try {
    var text = fetchText_(url);
    data = JSON.parse(text);
    if (!Array.isArray(data)) data = [data];
  } catch (e) {
    lines.push("(날씨 데이터를 가져오지 못했습니다: " + e + ")");
    return { prefix: "weather", content: lines.join("\n"), ok: false };
  }

  var validCount = 0;
  for (var i = 0; i < CITIES.length; i++) {
    var name = CITIES[i][0];
    var d = data[i];
    try {
      var expected = dateStamp_(now);
      if (!d.daily || !d.hourly || !Array.isArray(d.daily.time) || d.daily.time.length !== 1 ||
          d.daily.time[0] !== expected || !Array.isArray(d.hourly.time) || d.hourly.time.length !== 24 ||
          d.hourly.time.some(function (stamp, hour) { return stamp !== expected + "T" + pad2_(hour) + ":00"; }))
        throw new Error("Invalid source date or hours");
      var codes = d.hourly.weather_code;
      if (!Array.isArray(codes) || codes.length !== 24 || codes.some(function (code) {
        return ![0,1,2,3,45,48,51,53,55,56,57,61,63,65,66,67,71,73,75,77,80,81,82,85,86,95,96,99].includes(code);
      }) || !Number.isFinite(d.daily.temperature_2m_max[0]) || !Number.isFinite(d.daily.temperature_2m_min[0]) ||
          d.daily.temperature_2m_min[0] > d.daily.temperature_2m_max[0])
        throw new Error("Invalid source weather");
      var am = codes.slice(6, 12), pm = codes.slice(12, 18);
      var amE = codeToEmoji_(mostCommon_(am)), pmE = codeToEmoji_(mostCommon_(pm));
      var tmax = Math.round(d.daily.temperature_2m_max[0]);
      var tmin = Math.round(d.daily.temperature_2m_min[0]);
      lines.push("✫" + name + "(" + amE + ")➠(" + pmE + ")  " + tmin + "℃ ~ " + tmax + "℃");
      validCount++;
    } catch (e2) {
      lines.push("✫" + name + "(?)➠(?)  가져오기 실패");
    }
  }
  return { prefix: "weather", content: lines.join("\n") + "\n", ok: validCount === CITIES.length };
}

function fetchFortune_(now) {
  var month = now.getUTCMonth() + 1, day = now.getUTCDate();
  var header1 = "오늘의 운세, " + month + "월 " + day + "일";
  var keyword = month + "월 " + day + "일";
  var titleNeedle = "오늘의 운세, " + keyword;

  try {
    var searchUrl = "https://askjiyun.com/?mid=today&search_target=title&search_keyword=" + encodeURIComponent(keyword);
    var html = fetchText_(searchUrl);
    var bestSrl = null;
    var re = /<a[^>]+href="([^"]*document_srl=(\d+)[^"]*)"[^>]*>([\s\S]*?)<\/a>/g;
    var m;
    while ((m = re.exec(html)) !== null) {
      var text = stripTags_(m[3]);
      if (text !== titleNeedle) continue;
      var srl = parseInt(m[2], 10);
      if (bestSrl === null || srl > bestSrl) bestSrl = srl;
    }
    if (!bestSrl) {
      return { prefix: "fortune", content: header1 + "\n\n(오늘 날짜의 운세 글을 아직 찾지 못했습니다.)", ok: false };
    }
    var docUrl = "https://askjiyun.com/?mid=today&document_srl=" + bestSrl;
    var docHtml = fetchText_(docUrl);
    var bodyText = stripTags_(docHtml.replace(/<script[\s\S]*?<\/script>/g, "").replace(/<style[\s\S]*?<\/style>/g, ""));

    var startIdx = bodyText.indexOf("〈");
    var endIdx = bodyText.indexOf("이 게시물을");
    var body = (startIdx !== -1 && endIdx !== -1 && endIdx > startIdx) ? bodyText.slice(startIdx, endIdx) : bodyText;

    body = body.replace(/\s*(〈[^〉]+〉)\s*/g, "\n\n$1\n");
    body = body.replace(/(애정\s*\d+)\s*/g, "$1\n");
    body = body.replace(/\n{3,}/g, "\n\n");
    var lines = body.split("\n").map(function (l) { return l.trim(); }).filter(function (l) { return l; });
    body = lines.join("\n");
    body = body.replace(/\n〈/g, "\n\n〈");
    body = body.replace(/[ \t]*(운세지수 ?\d+%)/g, "\n\n$1");

    if (!body) {
      return { prefix: "fortune", content: header1 + "\n\n(오늘 날짜의 운세 글을 찾았지만 본문을 추출하지 못했습니다.)", ok: false };
    }
    return { prefix: "fortune", content: header1 + "\n\n" + body, ok: true };
  } catch (e) {
    return { prefix: "fortune", content: header1 + "\n\n(운세 데이터를 가져오지 못했습니다: " + e + ")", ok: false };
  }
}

var FX_LIST = [
  ["USD", "미국 달러"], ["JPY", "일본 엔(100)"], ["EUR", "유럽 유로"], ["CNY", "중국 위안"],
  ["GBP", "영국 파운드"], ["AUD", "호주 달러"], ["CAD", "캐나다 달러"], ["CHF", "스위스 프랑"],
  ["HKD", "홍콩 달러"], ["VND", "베트남 동(100)"]
];

function signFmt_(v, decimals) {
  var d = decimals === undefined ? 2 : decimals;
  var arrow = v > 0 ? "▲" : (v < 0 ? "▼" : "-");
  return arrow + Math.abs(v).toFixed(d);
}

function fetchMarket_(now) {
  var weekday = WEEKDAY_KR[weekdayIdx_(now)];
  var dateHead = (now.getUTCFullYear() % 100) + "년 " + (now.getUTCMonth() + 1) + "월 " + now.getUTCDate() + "일 " + weekday;

  var items = {};
  try {
    var mainHtml = fetchText_("https://finance.naver.com/marketindex/");
    var liRe = /<li[^>]*>([\s\S]*?)<\/li>/g, m;
    while ((m = liRe.exec(mainHtml)) !== null) {
      var t = stripTags_(m[1]);
      var mm = t.match(/^(휘발유|고급휘발유|경유|국제 금|국내 금)\s+([\d,]+\.?\d*)\s*(?:원|달러)\s+([\d,]+\.?\d*)\s+(상승|하락|보합)/);
      if (mm && !items[mm[1]]) {
        var val = parseFloat(mm[2].replace(/,/g, ""));
        var chg = parseFloat(mm[3].replace(/,/g, ""));
        if (mm[4] === "하락") chg = -chg; else if (mm[4] === "보합") chg = 0;
        items[mm[1]] = [val, chg];
      }
    }
  } catch (e) {}

  var dieselVal = null, dieselChg = null;
  try {
    var oilHtml = fetchText_("https://finance.naver.com/marketindex/oilDetail.naver?marketindexCd=OIL_LO");
    var todayM = oilHtml.match(/no_today[\s\S]*?>([\d,.]+)</);
    if (todayM) dieselVal = parseFloat(todayM[1].replace(/,/g, ""));
    var exM = oilHtml.match(/no_exday[\s\S]*?>([\s\S]*?)<\/p>/);
    if (exM) {
      var exText = stripTags_(exM[1]);
      var numM = exText.match(/([\d,]+\.?\d*)/);
      if (numM) {
        dieselChg = parseFloat(numM[1].replace(/,/g, ""));
        if (exText.indexOf("하락") !== -1) dieselChg = -dieselChg;
      }
    }
  } catch (e) {}

  var rates = {};
  try {
    var fxHtml = fetchText_("https://finance.naver.com/marketindex/exchangeList.naver");
    var trRe = /<tr>([\s\S]*?)<\/tr>/g, trm;
    while ((trm = trRe.exec(fxHtml)) !== null) {
      var tds = [];
      var tdRe = /<td[^>]*>([\s\S]*?)<\/td>/g, tdm;
      while ((tdm = tdRe.exec(trm[1])) !== null) tds.push(stripTags_(tdm[1]));
      if (tds.length < 2) continue;
      var name = tds[0];
      FX_LIST.forEach(function (pair) {
        var code = pair[0];
        if (name.indexOf(code) !== -1 && rates[code] === undefined) {
          var v = parseFloat(tds[1].replace(/,/g, ""));
          if (!isNaN(v)) rates[code] = v;
        }
      });
    }
  } catch (e) {}

  var props = PropertiesService.getScriptProperties();
  var prevRates = {};
  try { prevRates = JSON.parse(props.getProperty("FX_CACHE") || "{}"); } catch (e) {}

  var l1 = [dateHead + " 기름값·환율", "", "⛽ 전국 평균 기름값 (오피넷 기준, 전일 대비)", ""];
  var fuelRows = [];
  if (items["휘발유"]) fuelRows.push("휘발유 " + items["휘발유"][0].toFixed(2) + "원/L (" + signFmt_(items["휘발유"][1]) + ")");
  if (dieselVal !== null) {
    var chgS = dieselChg !== null ? " (" + signFmt_(dieselChg) + ")" : "";
    fuelRows.push("경유 " + dieselVal.toFixed(2) + "원/L" + chgS);
  }
  l1 = l1.concat(fuelRows.length ? fuelRows : ["(기름값을 가져오지 못했습니다)"]);
  l1.push(""); l1.push("💱 주요국 환율 (매매기준율, 전일 대비)"); l1.push("");
  var rateKeys = Object.keys(rates);
  if (rateKeys.length) {
    FX_LIST.forEach(function (pair) {
      var code = pair[0], label = pair[1];
      if (rates[code] === undefined) return;
      var cur = rates[code];
      var pct = "";
      if (prevRates[code]) {
        var p = (cur / prevRates[code] - 1) * 100;
        pct = " (" + (p >= 0 ? "+" : "") + p.toFixed(2) + "%)";
      }
      l1.push(label + " : " + cur.toFixed(2) + "원" + pct);
    });
    props.setProperty("FX_CACHE", JSON.stringify(rates));
  } else {
    l1.push("(환율을 가져오지 못했습니다)");
  }
  var fuelfx = l1.join("\n").trim() + "\n";

  var l2 = [dateHead + " 금·은·코인", "", "🥇 금·은 시세 (전일 대비)", ""];
  var metalRows = [];
  if (items["국제 금"]) metalRows.push("국제 금 " + items["국제 금"][0].toFixed(2) + "달러/온스 (" + signFmt_(items["국제 금"][1]) + ")");
  if (items["국내 금"]) metalRows.push("국내 금 " + items["국내 금"][0].toFixed(0) + "원/g (" + signFmt_(items["국내 금"][1], 0) + ")");
  try {
    var siText = fetchText_("https://query1.finance.yahoo.com/v8/finance/chart/SI%3DF?range=1d&interval=1d");
    var siJson = JSON.parse(siText);
    var siPrice = siJson.chart.result[0].meta.regularMarketPrice;
    metalRows.push("국제 은 " + siPrice.toFixed(2) + "달러/온스");
  } catch (e) {}
  l2 = l2.concat(metalRows.length ? metalRows : ["(금·은 시세를 가져오지 못했습니다)"]);
  l2.push(""); l2.push("🪙 코인 시가총액 상위 10 (24시간 등락)"); l2.push("");
  var COIN_KR = { BTC: "비트코인", ETH: "이더리움", XRP: "리플", BNB: "비앤비", SOL: "솔라나", DOGE: "도지코인",
    ADA: "에이다", TRX: "트론", LINK: "체인링크", AVAX: "아발란체", XLM: "스텔라루멘", SUI: "수이",
    HYPE: "하이퍼리퀴드", DOT: "폴카닷", LTC: "라이트코인", SHIB: "시바이누", TON: "톤코인", BCH: "비트코인캐시", HBAR: "헤데라" };
  var STABLES = { USDT: 1, USDC: 1, DAI: 1, FDUSD: 1, TUSD: 1, USDE: 1, BUSD: 1, PYUSD: 1, USDS: 1 };
  var coinRows = [];
  try {
    var coinUrl = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=krw&order=market_cap_desc&per_page=20&page=1&price_change_percentage=24h";
    var coinsJson = JSON.parse(fetchText_(coinUrl));
    if (!Array.isArray(coinsJson)) throw new Error("CoinGecko 응답 형식 오류");
    var count = 0;
    for (var ci = 0; ci < coinsJson.length && count < 10; ci++) {
      var c = coinsJson[ci];
      var sym = (c.symbol || "").toUpperCase();
      var name = c.name || "";
      if (STABLES[sym]) continue;
      if (/Staked|Wrapped|Bridged|Heloc/.test(name)) continue;
      if (!c.market_cap_rank || c.market_cap_rank > 30) continue;
      var price = c.current_price;
      var priceS = price >= 100 ? Math.round(price).toLocaleString() + "원" : price.toFixed(2) + "원";
      var pct = c.price_change_percentage_24h;
      var pctS = (pct !== null && pct !== undefined) ? " (" + (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%)" : "";
      coinRows.push((COIN_KR[sym] || sym) + " " + priceS + pctS);
      count++;
    }
  } catch (e) {}
  if (coinRows.length === 10) {
    props.setProperty("COIN_ROWS_CACHE_V1", JSON.stringify(coinRows));
    l2 = l2.concat(coinRows);
  } else {
    var cachedCoins = [];
    try { cachedCoins = JSON.parse(props.getProperty("COIN_ROWS_CACHE_V1") || "[]"); } catch (e) {}
    if (Array.isArray(cachedCoins) && cachedCoins.length === 10) l2 = l2.concat(cachedCoins);
  }
  var metalcoin = l2.join("\n").trim() + "\n";

  var l3 = [dateHead + " 주간 베스트셀러", "", "📚 알라딘 주간 베스트셀러 TOP 10", ""];
  try {
    var aladinHtml = fetchText_("https://www.aladin.co.kr/shop/common/wbest.aspx?BestType=Bestseller&BranchType=1&CID=0");
    var titles = [];
    var boRe = /<a[^>]+class="bo3"[^>]*>([\s\S]*?)<\/a>/g, bm;
    while ((bm = boRe.exec(aladinHtml)) !== null && titles.length < 10) {
      var tt = stripTags_(bm[1]);
      if (tt && titles.indexOf(tt) === -1) titles.push(tt);
    }
    if (titles.length) {
      titles.forEach(function (tt, idx) { l3.push((idx + 1) + ". " + tt); });
    } else {
      l3.push("(베스트셀러를 가져오지 못했습니다)");
    }
  } catch (e) {
    l3.push("(베스트셀러를 가져오지 못했습니다)");
  }
  var books = l3.join("\n").trim() + "\n";

  return {
    fuelfx: { prefix: "fuelfx", content: fuelfx, ok: !hasFetchFailure_(fuelfx) },
    metalcoin: { prefix: "metalcoin", content: metalcoin, ok: metalRows.length > 0 && coinRows.length === 10 },
    books: { prefix: "books", content: books, ok: !hasFetchFailure_(books) }
  };
}

var SHORTNEWS_URL = /^https:\/\/v\.daum\.net\/v\/[0-9]{10,20}$/;
var SHORTNEWS_ROW = /^\S+ \((톱뉴스|정치|경제|사회|국제|날씨)\) (.+)$/;
var KOSPI_ENDPOINTS = ["https://m.stock.naver.com/api/index/KOSPI/basic",
                       "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI"];
var WEATHER_DELAY = "[날씨 갱신 지연 · 당일 마지막 정상 예보 유지 · 최신 조회 실패]";

function shortnewsHeader_(now) {
  return (now.getUTCFullYear() % 100) + "년 " + (now.getUTCMonth() + 1) + "월 " +
    now.getUTCDate() + "일 " + WEEKDAY_KR[weekdayIdx_(now)] + " 오늘의 퀵뉴스⚡";
}

function validKospiClock_(stamp, now, status) {
  var age = now.getTime() - 32400000 - stamp.getTime();
  var kst = new Date(stamp.getTime() + 32400000);
  return Number.isFinite(age) && kst.getUTCDay() > 0 && kst.getUTCDay() < 6 &&
    age >= 0 && age <= 7 * 86400000 &&
    (status === "CLOSE" || (status === "OPEN" && dateStamp_(kst) === dateStamp_(now) && age <= 1800000));
}

function kospiLine_(now) {
  for (var i = 0; i < KOSPI_ENDPOINTS.length; i++) {
    try {
      var row = JSON.parse(fetchText_(KOSPI_ENDPOINTS[i]));
      if (Array.isArray(row.datas)) {
        var matches = row.datas.filter(function (entry) { return entry && entry.itemCode === "KOSPI"; });
        row = matches.length === 1 ? matches[0] : {};
      }
      var value = String(row.closePriceRaw === undefined ? row.closePrice : row.closePriceRaw);
      var exchange = row.stockExchangeType || row.exchange;
      if (row.itemCode !== "KOSPI" || !exchange || exchange.zoneId !== "Asia/Seoul" ||
          !/^(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?$/.test(value) ||
          !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$/.test(row.localTradedAt || "")) continue;
      var price = Number(value.replace(/,/g, ""));
      var status = row.marketStatus;
      var stamp = new Date(row.localTradedAt);
      if (!Number.isFinite(price) || price <= 0 || !validKospiClock_(stamp, now, status)) continue;
      var kst = new Date(stamp.getTime() + 32400000);
      if (!kst.toISOString().startsWith(row.localTradedAt.slice(0, 19))) continue;
      var closed = status === "CLOSE";
      var weekend = now.getUTCDay() === 0 || now.getUTCDay() === 6;
      var fixed = price.toFixed(2).replace(/\B(?=(\d{3})+\.)/g, ",");
      return "  - 코스피 : " + fixed + "pt (" + dateStamp_(kst) + (closed ? " 종가" : " 장중") +
        " · 네이버 표시 " + pad2_(kst.getUTCHours()) + ":" + pad2_(kst.getUTCMinutes()) + " KST" +
        (closed && weekend ? " · 주말 휴장" : "") + ")";
    } catch (e) {}
  }
  return "";
}

function quicknewsQuality_(content, now, allowUnverified) {
  if (!content || hasFetchFailure_(content)) return 0;
  var lines = content.trim().split(/\r?\n/);
  if (lines[0] !== shortnewsHeader_(now)) return 0;
  var quotes = lines.filter(function (line) { return /^\s*- 코스피 : /.test(line); });
  var priced = quotes.length === 1 && quotes[0].match(/^\s*- 코스피 : ((?:\d+|\d{1,3}(?:,\d{3})+)\.\d{2})pt \((\d{4}-\d{2}-\d{2}) (종가|장중) · 네이버 표시 (\d{2}:\d{2}) KST( · 주말 휴장)?\)$/);
  if (!lines.includes("[주요 경제 지표]") || quotes.length !== 1) return 0;
  if (!priced && !(allowUnverified && quotes[0].trim() === "- 코스피 : 시세 확인 대기 (제공처 값·기준시각 미확인)")) return 0;
  if (priced && !validQuicknewsQuote_(priced, now)) return 0;
  var labels = {}, count = 0, seen = {};
  for (var i = 0; i < lines.length; i++) {
    var row = lines[i].match(SHORTNEWS_ROW);
    if (!row) continue;
    var url = lines[i + 1] || "";
    if (allowUnverified && url === "원문 링크 미확인") {
      labels[row[1]] = true; count++; continue;
    }
    if (!SHORTNEWS_URL.test(url) || seen[url]) return 0;
    seen[url] = true; labels[row[1]] = true; count++;
  }
  return count >= 8 && ["정치", "경제", "사회", "국제"].every(function (label) { return labels[label]; }) ? count : 0;
}

function validQuicknewsQuote_(priced, now) {
  var quoteClock = priced[2] + "T" + priced[4];
  var quoteDate = new Date(quoteClock + ":00+09:00");
  var weekend = now.getUTCDay() === 0 || now.getUTCDay() === 6;
  var price = Number(priced[1].replace(/,/g, ""));
  return Number.isFinite(price) && price > 0 &&
    validKospiClock_(quoteDate, now, priced[3] === "종가" ? "CLOSE" : "OPEN") &&
    new Date(quoteDate.getTime() + 32400000).toISOString().startsWith(quoteClock) &&
    Boolean(priced[5]) === (weekend && priced[3] === "종가");
}

function fetchShortnews_(now) {
  var sections = [[["politics"], "정치", "🏛️", 3], [["economic", "economy"], "경제", "💰", 5],
                  [["society"], "사회", "👥", 5], [["foreign", "world"], "국제", "🌏", 2]];
  var lines = [shortnewsHeader_(now), ""], seen = {};
  var today = dateStamp_(now).replace(/-/g, "");
  var yesterday = dateStamp_(new Date(now.getTime() - 86400000)).replace(/-/g, "");
  sections.forEach(function (sec) {
    var count = 0;
    for (var i = 0; i < sec[0].length && count < sec[3]; i++) {
      try {
        var page = fetchText_("https://news.daum.net/" + sec[0][i]);
        var re = /<a\b([^>]*\bhref=["'](https:\/\/v\.daum\.net\/v\/(20\d{6}\d{2,12}))["'][^>]*)>([\s\S]*?)<\/a>/g;
        var m;
        while (count < sec[3] && (m = re.exec(page)) !== null) {
          if (seen[m[2]] || m[3].slice(0, 8) < yesterday || m[3].slice(0, 8) > today) continue;
          var encoded = m[1].match(/\bdata-title=["']([^"']+)["']/);
          var heading = m[4].match(/<(strong|h2|h3)\b[^>]*>([\s\S]*?)<\/\1>/i);
          var title = encoded ? htmlUnescape_(decodeURIComponent(encoded[1])) :
            (heading ? stripTags_(heading[2]) : "");
          title = title.replace(/\s+/g, " ").trim();
          if (title.length < 10) continue;
          seen[m[2]] = true;
          lines.push(sec[2] + " (" + sec[1] + ") " + title, m[2], "");
          count++;
        }
      } catch (e) {}
    }
  });
  var quote = kospiLine_(now);
  if (quote) lines.push("[주요 경제 지표]", quote);
  var content = lines.join("\n").trim() + "\n";
  return quicknewsQuality_(content, now) ? content : "";
}

function ghConfig_() {
  var p = PropertiesService.getScriptProperties();
  return {
    token: p.getProperty("GITHUB_TOKEN"),
    owner: p.getProperty("REPO_OWNER") || "busanfransisco-source",
    repo: p.getProperty("REPO_NAME") || "naver-realestate-bot"
  };
}

function ghRequest_(cfg, endpoint, method, payload) {
  var options = {
    method: method || "get", muteHttpExceptions: true,
    headers: { Authorization: "Bearer " + cfg.token, Accept: "application/vnd.github+json" }
  };
  if (payload) {
    options.contentType = "application/json";
    options.payload = JSON.stringify(payload);
  }
  var response = UrlFetchApp.fetch("https://api.github.com/repos/" + cfg.owner + "/" + cfg.repo + endpoint, options);
  var code = response.getResponseCode();
  if (method === undefined && code === 404 && endpoint.startsWith("/contents/")) return null;
  if (code < 200 || code >= 300) throw new Error("GitHub " + (method || "get") + " HTTP " + code);
  return JSON.parse(response.getContentText());
}

function ghGetTextFile_(path, ref, cfg) {
  var entry = ghRequest_(cfg || ghConfig_(), "/contents/" + encodeURIComponent(path) +
    "?ref=" + encodeURIComponent(ref || "main"));
  if (!entry) return null;
  if (entry.encoding !== "base64" || typeof entry.content !== "string") throw new Error("Unreadable GitHub file: " + path);
  return Utilities.newBlob(Utilities.base64Decode(entry.content.replace(/\n/g, "")), "text/plain").getDataAsString("UTF-8");
}

function commitBackup_(cfg, base, changes, day) {
  var parent = ghRequest_(cfg, "/git/commits/" + base);
  var entries = Object.keys(changes).map(function (path) {
    return {path: path, type: "blob", mode: "100644", content: changes[path]};
  });
  var tree = ghRequest_(cfg, "/git/trees", "post", {base_tree: parent.tree.sha, tree: entries});
  var target = ghRequest_(cfg, "/git/commits", "post", {
    message: "Backup pipeline refresh (Apps Script) " + day, tree: tree.sha, parents: [base]
  });
  // A regular, non-forced fast-forward rejects a concurrent main publication.
  ghRequest_(cfg, "/git/refs/heads/main", "patch", {sha: target.sha, force: false});
}

function escapeHtml_(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function readCardBody_(page, key) {
  var pattern = new RegExp('<textarea id="ta-' + key + '"[^>]*>([\\s\\S]*?)<\\/textarea>');
  var match = page.match(pattern);
  return match ? htmlUnescape_(match[1]).trim() : "";
}

function rebuildBackupCard_(page, key, content) {
  var area = new RegExp('(<textarea id="ta-' + key + '"[^>]*>)[\\s\\S]*?(<\\/textarea>)','g');
  var copy = new RegExp('(window\\.__content_' + key + ' = )"(?:\\\\.|[^"\\\\])*"(;)', 'g');
  if ((page.match(area) || []).length !== 1 || (page.match(copy) || []).length !== 1)
    throw new Error("Unexpected briefing card: " + key);
  var body = content.trim();
  page = page.replace(area, function (_, start, end) { return start + escapeHtml_(body) + end; });
  page = page.replace(copy, function (_, start, end) {
    return start + JSON.stringify(body).replace(/</g, "\\u003c") + end;
  });
  if (key === "shortnews") {
    var preview = /(<div id="preview-shortnews"[^>]*>)[\s\S]*?(<\/div>)/g;
    if ((page.match(preview) || []).length !== 1) throw new Error("Quick news link preview missing");
    var display = body.split("\n").map(function (line) {
      var escaped = escapeHtml_(line);
      return SHORTNEWS_URL.test(line) ? '<a class="news-source-link" href="' + escaped +
        '" target="_blank" rel="noopener noreferrer">' + escaped + '</a>' : escaped;
    }).join("\n");
    page = page.replace(preview, function (_, start, end) { return start + display + end; });
  }
  return page;
}

function buildBriefingHtml_(now, sections, existing) {
  var slots = existing.match(/<section class="card" data-slot="\d+"/g) || [];
  if (slots.length !== 30 || new Set(slots).size !== 30 || !existing.includes('id="auth-gate"') ||
      !existing.includes('id="preview-shortnews"')) throw new Error("Canonical briefing layout unavailable");
  var page = existing;
  Object.keys(sections).forEach(function (key) { page = rebuildBackupCard_(page, key, sections[key]); });
  return page;
}

function isTodayAlreadyRefreshed_(now) {
  try {
    var text = ghGetTextFile_("last-refresh.txt");
    if (!text) return false;
    var refreshedAt = new Date(text.trim());
    var diffMs = now.getTime() - 9 * 60 * 60 * 1000 - refreshedAt.getTime();
    var diffHours = diffMs / 1000 / 60 / 60;
    return diffHours < 3;
  } catch (e) {
    return false;
  }
}

function runBackupIfNeeded() {
  var now = nowKST_();

  if (isTodayAlreadyRefreshed_(now)) {
    Logger.log("GitHub Actions가 이미 최근에 갱신함 - 백업 실행 건너뜀");
    return;
  }
  Logger.log("GitHub Actions 갱신이 오래됨 - 백업 파이프라인 실행 시작");
  runBackupNow();
}

function sameDayWeather_(body, now) {
  var header = now.getUTCFullYear() + "년 " + (now.getUTCMonth() + 1) + "월 " +
    now.getUTCDate() + "일 " + WEEKDAY_KR[weekdayIdx_(now)];
  body = (body || "").replace(/\r\n/g, "\n");
  if (!body.startsWith(header + "\n") || !body.includes("❒ 지역별 날씨전망 ❒")) return "";
  var rows = body.split(/\r?\n/).filter(function (line) { return line.startsWith("✫"); });
  if (rows.length !== CITIES.length || !rows.every(function (line, i) {
    var match = line.match(/^✫([^()]+)\([^()]+\)➠\([^()]+\)  (-?\d+)℃ ~ (-?\d+)℃$/);
    return match && match[1] === CITIES[i][0] && Number(match[2]) >= -90 &&
      Number(match[2]) <= Number(match[3]) && Number(match[3]) <= 60;
  })) return "";
  return [header, "", "❒ 지역별 날씨전망 ❒", ""].concat(rows).join("\n");
}

function runBackupNow() {
  var now = nowKST_(), today = dateStamp_(now), weekday = WEEKDAY_EN[weekdayIdx_(now)];
  var cfg = ghConfig_();
  var base = ghRequest_(cfg, "/git/ref/heads/main").object.sha;
  function read(path) { return ghGetTextFile_(path, base, cfg); }
  var existing = read("briefing.html");
  if (!existing) throw new Error("Canonical briefing page unavailable");
  var results = {}, changes = {}, errors = [];

  function save(result) {
    if (result && result.ok && !hasFetchFailure_(result.content)) {
      var key = result.prefix;
      results[key] = result.content;
      changes[key + ".txt"] = result.content;
      changes[key + "-" + weekday + ".txt"] = result.content;
    }
  }

  var status;
  try { status = JSON.parse(read("weather-status.txt")); } catch (e) { status = null; }
  var age = now.getTime() - 32400000 -
    Date.parse(status && (status.failedAtKst || status.attemptedAtKst));
  var deferred = status && status.status === "failed" && age >= 0 && age < 600000;
  var storedWeather = read("weather-" + today + ".txt");
  var lastWeather = sameDayWeather_(storedWeather, now) ||
    sameDayWeather_(read("weather-" + weekday + ".txt"), now) ||
    sameDayWeather_(read("weather.txt"), now) ||
    sameDayWeather_(readCardBody_(existing, "weather").replace(WEATHER_DELAY + "\n", ""), now);
  if (!lastWeather && !deferred) {
    var attempt = now.toISOString().replace("Z", "+09:00");
    var forecast = fetchWeather_(now);
    var validated = forecast.ok && sameDayWeather_(forecast.content, now);
    var weatherStatus = {forecastDate: today, attemptedAtKst: attempt, status: validated ? "ok" : "failed"};
    if (validated) {
      save({prefix: "weather", content: validated, ok: true});
      changes["weather-" + today + ".txt"] = validated;
    } else {
      weatherStatus.failedAtKst = nowKST_().toISOString().replace("Z", "+09:00");
      weatherStatus.errorType = "BackupSourceUnavailable";
    }
    changes["weather-status.txt"] = JSON.stringify(weatherStatus) + "\n";
  }
  if (!results.weather) {
    results.weather = lastWeather ||
      "당일 날씨 자료를 확보하지 못했습니다. 갱신을 기다리고 있습니다.";
  }

  var quickFile = "shortnews-" + weekday + ".txt";
  var currentQuick = readCardBody_(existing, "shortnews");
  var savedQuick = read(quickFile);
  var generalQuick = read("shortnews.txt");
  // Prefer the canonical article summaries, including explicit unverified fields.
  var candidates = [currentQuick, savedQuick, generalQuick];
  var quick = candidates.find(function (candidate) { return quicknewsQuality_(candidate, now); }) ||
    candidates.find(function (candidate) { return quicknewsQuality_(candidate, now, true); });
  if (!quick) quick = fetchShortnews_(now);
  if (quick) {
    var cleaned = quick.trim();
    if (currentQuick !== cleaned) results.shortnews = cleaned;
    if (!savedQuick || savedQuick.trim() !== cleaned) changes[quickFile] = cleaned + "\n";
    if (!generalQuick || generalQuick.trim() !== cleaned) changes["shortnews.txt"] = cleaned + "\n";
  } else {
    errors.push("shortnews: no verified article links and KOSPI");
  }

  [fetchFortune_, fetchRealestateNews_, fetchWorldNews_, fetchFinanceNews_, fetchAiNews_].forEach(function (fetcher) {
    try { save(fetcher(now)); } catch (e) { errors.push(fetcher.name); }
  });
  try {
    var market = fetchMarket_(now);
    [market.fuelfx, market.metalcoin, market.books].forEach(save);
  } catch (e) { errors.push("market"); }

  var page = buildBriefingHtml_(now, results, existing);
  if (page !== existing) changes["briefing.html"] = page;
  changes["last-refresh-backup.txt"] = new Date().toISOString() + "\n";
  commitBackup_(cfg, base, changes, today);
  Logger.log("백업 파이프라인 완료. 확인 실패: " + (errors.length ? errors.join(" | ") : "없음"));
}

/**
 * 06:30 안전망: 오늘 06:00(KST) 이후에 주 파이프라인이 갱신하지 못했으면
 * 백업을 강제 실행한다. 03:55처럼 이른 갱신은 여기서 "완료"로 보지 않는다.
 */
function isMorningRefreshComplete_(now) {
  try {
    var text = ghGetTextFile_("last-refresh.txt");
    if (!text) return false;
    var refreshedKST = new Date(new Date(text.trim()).getTime() + 9 * 60 * 60 * 1000);
    return refreshedKST.getUTCFullYear() === now.getUTCFullYear() &&
      refreshedKST.getUTCMonth() === now.getUTCMonth() &&
      refreshedKST.getUTCDate() === now.getUTCDate() &&
      refreshedKST.getUTCHours() >= 6;
  } catch (e) { return false; }
}

function runMorningBackupSafetyNet() {
  var now = nowKST_();
  if (isMorningRefreshComplete_(now)) {
    Logger.log("오늘 06시 이후 주 파이프라인 갱신 확인 - 아침 백업 건너뜀");
    return;
  }
  Logger.log("오늘 06시 이후 갱신 없음 - 아침 백업 안전망 실행");
  runBackupNow();
}

function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var handler = t.getHandlerFunction();
    if (handler === "runBackupIfNeeded" || handler === "runMorningBackupSafetyNet") {
      ScriptApp.deleteTrigger(t);
    }
  });
  [7, 12, 15, 21].forEach(function (hourKST) {
    ScriptApp.newTrigger("runBackupIfNeeded")
      .timeBased().everyDays(1).atHour(hourKST).create();
  });
  ScriptApp.newTrigger("runBackupIfNeeded")
    .timeBased().everyDays(1).atHour(6).nearMinute(0).create();
  ScriptApp.newTrigger("runMorningBackupSafetyNet")
    .timeBased().everyDays(1).atHour(6).nearMinute(30).create();
  Logger.log("트리거 6개 설정 완료: 06:00 점검, 06:30 아침 안전망, 07/12/15/21시 일반 점검");
}
