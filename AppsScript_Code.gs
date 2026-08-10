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
 *  4) 오래됐으면(=GitHub Actions가 멈춘 상태로 판단) 직접 뉴스/시세를
 *     긁어와서 briefing.html을 새로 만들고 GitHub Contents API로 커밋
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

  for (var i = 0; i < CITIES.length; i++) {
    var name = CITIES[i][0];
    var d = data[i];
    try {
      var codes = d.hourly.weather_code;
      var am = codes.slice(6, 12), pm = codes.slice(12, 18);
      var amE = codeToEmoji_(mostCommon_(am)), pmE = codeToEmoji_(mostCommon_(pm));
      var tmax = Math.round(d.daily.temperature_2m_max[0]);
      var tmin = Math.round(d.daily.temperature_2m_min[0]);
      lines.push("✫" + name + "(" + amE + ")➠(" + pmE + ")  " + tmin + "℃ ~ " + tmax + "℃");
    } catch (e2) {
      lines.push("✫" + name + "(?)➠(?)  가져오기 실패");
    }
  }
  return { prefix: "weather", content: lines.join("\n") + "\n", ok: true };
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
  try {
    var coinUrl = "https://api.coingecko.com/api/v3/coins/markets?vs_currency=krw&order=market_cap_desc&per_page=20&page=1&price_change_percentage=24h";
    var coinsJson = JSON.parse(fetchText_(coinUrl));
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
      l2.push((COIN_KR[sym] || sym) + " " + priceS + pctS);
      count++;
    }
    if (count === 0) l2.push("(코인 시세를 가져오지 못했습니다)");
  } catch (e) {
    l2.push("(코인 시세를 가져오지 못했습니다)");
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
    fuelfx: { prefix: "fuelfx", content: fuelfx, ok: true },
    metalcoin: { prefix: "metalcoin", content: metalcoin, ok: true },
    books: { prefix: "books", content: books, ok: true }
  };
}

function fetchShortnews_(now) {
  var weekday = WEEKDAY_KR[weekdayIdx_(now)];
  var header = (now.getUTCFullYear() % 100) + "년 " + (now.getUTCMonth() + 1) + "월 " + now.getUTCDate() + "일 " + weekday + " 오늘의 퀵뉴스⚡";
  var SECTIONS = [["politics", "정치", "🏛️", 3], ["economic", "경제", "💰", 5], ["society", "사회", "👥", 5], ["foreign", "국제", "🌏", 2]];
  var lines = [header, ""];
  var any = false;
  SECTIONS.forEach(function (sec) {
    var slug = sec[0], label = sec[1], emoji = sec[2], want = sec[3];
    try {
      var html = fetchText_("https://news.daum.net/" + slug);
      var re = /<a[^>]+href="(https:\/\/v\.daum\.net\/v\/\d+)"[^>]*>([\s\S]*?)<\/a>/g;
      var m, cnt = 0, seen = {};
      while ((m = re.exec(html)) !== null && cnt < want) {
        var title = stripTags_(m[2]);
        if (!title || title.length < 10 || seen[m[1]]) continue;
        seen[m[1]] = true;
        lines.push(emoji + " (" + label + ") " + title);
        lines.push("");
        cnt++; any = true;
      }
    } catch (e) {}
  });
  if (!any) { lines.push("(오늘 뉴스 수집에 실패했습니다)"); lines.push(""); }
  return { prefix: "shortnews", content: lines.join("\n").trim() + "\n", ok: any };
}

function ghConfig_() {
  var p = PropertiesService.getScriptProperties();
  return {
    token: p.getProperty("GITHUB_TOKEN"),
    owner: p.getProperty("REPO_OWNER") || "busanfransisco-source",
    repo: p.getProperty("REPO_NAME") || "naver-realestate-bot"
  };
}

function ghGetFile_(path) {
  var cfg = ghConfig_();
  var url = "https://api.github.com/repos/" + cfg.owner + "/" + cfg.repo + "/contents/" + encodeURIComponent(path);
  var resp = UrlFetchApp.fetch(url, {
    headers: { Authorization: "Bearer " + cfg.token, Accept: "application/vnd.github+json" },
    muteHttpExceptions: true
  });
  if (resp.getResponseCode() !== 200) return null;
  return JSON.parse(resp.getContentText());
}

function ghPutFile_(path, content, message) {
  var cfg = ghConfig_();
  var url = "https://api.github.com/repos/" + cfg.owner + "/" + cfg.repo + "/contents/" + encodeURIComponent(path);
  var existing = ghGetFile_(path);
  var payload = {
    message: message,
    content: Utilities.base64Encode(content, Utilities.Charset.UTF_8),
    branch: "main"
  };
  if (existing && existing.sha) payload.sha = existing.sha;
  var resp = UrlFetchApp.fetch(url, {
    method: "put",
    contentType: "application/json",
    headers: { Authorization: "Bearer " + cfg.token, Accept: "application/vnd.github+json" },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  var code = resp.getResponseCode();
  if (code !== 200 && code !== 201) {
    throw new Error("GitHub commit 실패 (" + path + "): " + code + " " + resp.getContentText());
  }
}

function ghGetTextFile_(path) {
  var f = ghGetFile_(path);
  if (!f || !f.content) return null;
  return Utilities.newBlob(Utilities.base64Decode(f.content.replace(/\n/g, "")), "text/plain").getDataAsString("UTF-8");
}

function escapeHtml_(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function buildBriefingHtml_(now, sections) {
  var weekday = WEEKDAY_KR[weekdayIdx_(now)];
  var dateLine = now.getUTCFullYear() + "년 " + (now.getUTCMonth() + 1) + "월 " + now.getUTCDate() + "일 " + weekday;
  var hh = pad2_(now.getUTCHours()), mm = pad2_(now.getUTCMinutes());
  var updateLine = (now.getUTCMonth() + 1) + "월 " + now.getUTCDate() + "일 " + hh + ":" + mm;
  var buildDate = dateStamp_(now);

  var order = [
    ["fortune", "🔮 오늘의 운세"], ["weather", "☀️ 날씨"], ["shortnews", "⚡ 오늘의 퀵뉴스"],
    ["subs", "🏗️ 청약 소식"], ["trend", "📈 부동산 주간 시세동향"], ["fuelfx", "⛽ 기름값·환율"],
    ["metalcoin", "🥇 금·은·코인"], ["books", "📚 주간 베스트셀러"], ["realestate", "🏠 부동산 뉴스"],
    ["world", "🌏 세계 뉴스"], ["finance", "🏦 금융 뉴스"], ["ai", "🤖 AI 뉴스"]
  ];

  var blocks = order.map(function (pair) {
    var key = pair[0], label = pair[1];
    var content = (sections[key] || "(데이터 없음)").replace(/\n+$/, "");
    var escaped = escapeHtml_(content);
    return '\n<section class="card">\n<div class="card-head">\n<h2>' + label + '</h2>\n' +
      '<button class="copy-btn" onclick="copySection(\'' + key + '\', this)">복사</button>\n</div>\n' +
      '<textarea id="ta-' + key + '" class="preview" readonly>' + escaped + '</textarea>\n' +
      '<script>window.__content_' + key + ' = ' + JSON.stringify(content) + ';</script>\n</section>';
  }).join("\n");

  return '<!DOCTYPE html>\n<html lang="ko">\n<head>\n<meta charset="UTF-8">\n' +
    '<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">\n' +
    '<title>오늘의 브리핑</title>\n<style>\n* { box-sizing: border-box; }\nbody { margin:0;padding:16px;' +
    'font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;' +
    'background:#f4f4f5;color:#1a1a1a; }\nh1{font-size:18px;margin:4px 0 16px;text-align:center;color:#444;}\n' +
    '.update-time{text-align:center;font-size:12px;color:#999;margin:-12px 0 16px;}\n' +
    '.card{background:#fff;border-radius:14px;padding:14px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,0.08);}\n' +
    '.card-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;}\n' +
    '.card-head h2{font-size:17px;margin:0;}\n' +
    '.copy-btn{font-size:15px;font-weight:600;padding:10px 20px;border:none;border-radius:10px;background:#3b82f6;color:#fff;cursor:pointer;min-width:76px;}\n' +
    '.copy-btn.copied{background:#22c55e;}\n' +
    '.preview{width:100%;height:130px;resize:vertical;font-size:13px;line-height:1.5;color:#555;border:1px solid #e5e5e5;border-radius:8px;padding:8px;background:#fafafa;white-space:pre-wrap;}\n' +
    '</style>\n</head>\n<body>\n<h1>📅 ' + dateLine + '</h1>\n' +
    '<p class="update-time">🕐 마지막 업데이트(백업 파이프라인): ' + updateLine + '</p>\n' +
    blocks + '\n\n<script>\nvar BUILD_DATE = \'' + buildDate + '\';\n(function(){\nvar d=new Date();\n' +
    "var today = d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');\n" +
    "if(today!==BUILD_DATE && location.search.indexOf('r=')===-1){location.replace(location.pathname+'?r='+Date.now());}\n" +
    "})();\nfunction markCopied(btn){var o=btn.textContent;btn.textContent='복사됨';btn.classList.add('copied');" +
    "setTimeout(function(){btn.textContent=o;btn.classList.remove('copied');},1200);}\n" +
    "function copySection(key,btn){var ta=document.getElementById('ta-'+key);var copied=false;try{" +
    "ta.style.position='fixed';ta.style.top='0';ta.focus();ta.select();ta.setSelectionRange(0,ta.value.length);" +
    "copied=document.execCommand('copy');}catch(e){copied=false;}if(copied){markCopied(btn);return;}" +
    "var text=window['__content_'+key];if(navigator.clipboard&&navigator.clipboard.writeText){" +
    "navigator.clipboard.writeText(text).then(function(){markCopied(btn);}).catch(function(){" +
    "alert('복사에 실패했습니다.');});}else{alert('복사에 실패했습니다.');}}\n</script>\n</body>\n</html>\n";
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

function runBackupNow() {
  var now = nowKST_();
  var weekday_en = WEEKDAY_EN[weekdayIdx_(now)];
  var today = dateStamp_(now);

  var results = {};
  var errors = [];

  function safeRun(name, fn) {
    try {
      var r = fn();
      if (r && r.prefix) results[r.prefix] = r.content;
      return r;
    } catch (e) {
      errors.push(name + ": " + e);
      return null;
    }
  }

  safeRun("weather", function () { return fetchWeather_(now); });
  safeRun("fortune", function () { return fetchFortune_(now); });
  safeRun("realestate", function () { return fetchRealestateNews_(now); });
  safeRun("shortnews", function () { return fetchShortnews_(now); });
  safeRun("world", function () { return fetchWorldNews_(now); });
  safeRun("finance", function () { return fetchFinanceNews_(now); });
  safeRun("ai", function () { return fetchAiNews_(now); });

  try {
    var market = fetchMarket_(now);
    results.fuelfx = market.fuelfx.content;
    results.metalcoin = market.metalcoin.content;
    results.books = market.books.content;
  } catch (e) {
    errors.push("market: " + e);
  }

  ["subs", "trend"].forEach(function (key) {
    var existing = ghGetTextFile_(key + "-" + weekday_en + ".txt");
    if (existing) results[key] = existing;
  });

  var html = buildBriefingHtml_(now, results);

  ghPutFile_("briefing.html", html, "Backup pipeline refresh (Apps Script) " + today);
  ghPutFile_("last-refresh-backup.txt", now.toISOString(), "Backup pipeline timestamp " + today);

  Object.keys(results).forEach(function (key) {
    if (["subs", "trend"].indexOf(key) !== -1) return;
    try {
      ghPutFile_(key + ".txt", results[key], "Backup pipeline data: " + key);
      ghPutFile_(key + "-" + weekday_en + ".txt", results[key], "Backup pipeline data: " + key);
    } catch (e) {
      errors.push("commit " + key + ": " + e);
    }
  });

  Logger.log("백업 파이프라인 완료. 에러: " + (errors.length ? errors.join(" | ") : "없음"));
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
