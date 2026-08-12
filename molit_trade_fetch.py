# -*- coding: utf-8 -*-
"""
국토교통부 아파트매매 실거래자료 수집 (RTMSDataSvcAptTradeDev, data.go.kr)
------------------------------------------------------------------------
목적: "신고가 단지 탐지"를 위한 우리 저장소(raw + SQLite) 구축.
신고가 판별 로직 자체는 이 스크립트의 범위가 아니다 (별도 분석 단계에서 처리).

계층 구조:
  1) raw:  data/trades/{법정동코드}/{계약월YYYYMM}.json  (API 원본을 정규화한 리스트)
  2) db:   trades.db (SQLite) — raw json들로부터 매 실행마다 재구성/증분 반영. git에는 커밋하지 않음.
  3) state: molit_backfill_state.json — 과거분 백필 진행 상황 체크포인트 (git 커밋 대상)

동작 모드:
  --mode incremental (기본): 이번 달 + 지난달 데이터를 전 지역에 대해 항상 재수집(늦게 신고되는 거래 반영)
  --mode backfill: 최근 3년치 중 아직 못 받은 (지역, 월) 조합을 예산(MOLIT_BACKFILL_BUDGET) 안에서 이어받기
  --mode all: incremental 먼저, 남는 예산으로 backfill 이어서 (일일 워크플로우 기본값)

429/트래픽 한도 초과 시: 현재까지 진행 상황을 저장하고 조용히 종료한다 (다음 실행에서 이어받음).
"""
import argparse
import json
import os
import sqlite3
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from molit_regions import REGIONS

KST = timezone(timedelta(hours=9))
API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTradeDev/getRTMSDataSvcAptTradeDev"
MOLIT_KEY = os.environ.get("MOLIT_KEY", "")

RAW_DIR = "data/trades"
DB_PATH = "trades.db"
STATE_PATH = "molit_backfill_state.json"

BACKFILL_MONTHS = 36  # 최근 3년치
BACKFILL_BUDGET = int(os.environ.get("MOLIT_BACKFILL_BUDGET", "200"))  # 실행당 (지역,월) 조합 수

QUOTA_ERROR_CODES = {"22", "29", "30"}  # 트래픽 초과/키 미등록 계열
HEADERS = {"User-Agent": "Mozilla/5.0"}


class QuotaExceeded(Exception):
    pass


def month_str(dt):
    return f"{dt.year:04d}{dt.month:02d}"


def add_months(dt, delta):
    y, m = dt.year, dt.month + delta
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return dt.replace(year=y, month=m, day=1)


def _text(item, tag):
    el = item.find(tag)
    return el.text.strip() if el is not None and el.text else ""


def _to_int(s, default=None):
    s = (s or "").replace(",", "").strip()
    try:
        return int(s)
    except ValueError:
        return default


def _to_float(s, default=None):
    s = (s or "").strip()
    try:
        return float(s)
    except ValueError:
        return default


def call_api(lawd_cd, deal_ymd, page, tries=5):
    params = {
        "serviceKey": MOLIT_KEY,
        "LAWD_CD": lawd_cd,
        "DEAL_YMD": deal_ymd,
        "pageNo": page,
        "numOfRows": 1000,
    }
    for i in range(tries):
        try:
            resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=25)
        except requests.RequestException:
            time.sleep(3 * (i + 1))
            continue
        if resp.status_code == 429:
            raise QuotaExceeded(f"HTTP 429 ({lawd_cd} {deal_ymd})")
        if resp.status_code != 200:
            time.sleep(3 * (i + 1))
            continue
        try:
            root = ET.fromstring(resp.text)
        except ET.ParseError:
            time.sleep(3 * (i + 1))
            continue
        result_code = _text(root, "./header/resultCode") or _text(root, "./cmmMsgHeader/returnReasonCode")
        if result_code and result_code not in ("00", "0"):
            if result_code in QUOTA_ERROR_CODES:
                raise QuotaExceeded(f"resultCode={result_code} ({lawd_cd} {deal_ymd})")
            result_msg = _text(root, "./header/resultMsg")
            raise RuntimeError(f"API error {result_code} {result_msg} ({lawd_cd} {deal_ymd})")
        return root
    raise RuntimeError(f"failed after {tries} tries ({lawd_cd} {deal_ymd})")


def fetch_region_month(lawd_cd, deal_ymd):
    """해당 지역·월의 전체 거래 내역을 정규화된 dict 리스트로 반환."""
    records = []
    page = 1
    total_count = None
    while True:
        root = call_api(lawd_cd, deal_ymd, page)
        total_count = _to_int(_text(root, "./body/totalCount"), total_count or 0)
        items = root.findall("./body/items/item")
        if not items:
            break
        for item in items:
            price = _to_int(_text(item, "dealAmount"))
            records.append({
                "region_code": lawd_cd,
                "apt_seq": _text(item, "aptSeq"),
                "apt_name": _text(item, "aptNm"),
                "dong": _text(item, "umdNm"),
                "jibun": _text(item, "jibun"),
                "area": _to_float(_text(item, "excluUseAr")),
                "floor": _to_int(_text(item, "floor")),
                "deal_year": _to_int(_text(item, "dealYear")),
                "deal_month": _to_int(_text(item, "dealMonth")),
                "deal_day": _to_int(_text(item, "dealDay")),
                "price": price,
                "build_year": _to_int(_text(item, "buildYear")),
                "cancel_deal": _text(item, "cdealDay"),
                "dealing_type": _text(item, "dealingGbn"),
            })
        if total_count and len(records) >= total_count:
            break
        page += 1
        time.sleep(0.3)
    return records


def save_raw(lawd_cd, deal_ymd, records):
    region_dir = os.path.join(RAW_DIR, lawd_cd)
    os.makedirs(region_dir, exist_ok=True)
    path = os.path.join(region_dir, f"{deal_ymd}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, separators=(",", ":"))
    return path


def load_raw(lawd_cd, deal_ymd):
    path = os.path.join(RAW_DIR, lawd_cd, f"{deal_ymd}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------- SQLite ----------------

def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            region_code TEXT NOT NULL,
            apt_seq TEXT,
            apt_name TEXT,
            dong TEXT,
            jibun TEXT,
            area REAL,
            floor INTEGER,
            deal_year INTEGER,
            deal_month INTEGER,
            deal_day INTEGER,
            price INTEGER,
            build_year INTEGER,
            cancel_deal TEXT,
            dealing_type TEXT,
            UNIQUE(region_code, apt_name, dong, jibun, area, floor,
                   deal_year, deal_month, deal_day, price)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_lookup
        ON trades(region_code, apt_name, dong, area)
    """)
    return conn


def upsert_region_month(conn, lawd_cd, deal_ymd, records):
    year, mon = int(deal_ymd[:4]), int(deal_ymd[4:6])
    conn.execute(
        "DELETE FROM trades WHERE region_code=? AND deal_year=? AND deal_month=?",
        (lawd_cd, year, mon),
    )
    conn.executemany(
        """INSERT OR IGNORE INTO trades
           (region_code, apt_seq, apt_name, dong, jibun, area, floor,
            deal_year, deal_month, deal_day, price, build_year, cancel_deal, dealing_type)
           VALUES (:region_code, :apt_seq, :apt_name, :dong, :jibun, :area, :floor,
                   :deal_year, :deal_month, :deal_day, :price, :build_year, :cancel_deal, :dealing_type)""",
        records,
    )
    conn.commit()


def rebuild_db_from_raw(conn):
    """trades.db가 없거나(신규 러너) 오래됐을 때 raw json 전체로부터 재구성."""
    if not os.path.isdir(RAW_DIR):
        return
    for lawd_cd in os.listdir(RAW_DIR):
        region_dir = os.path.join(RAW_DIR, lawd_cd)
        if not os.path.isdir(region_dir):
            continue
        for fname in os.listdir(region_dir):
            if not fname.endswith(".json"):
                continue
            deal_ymd = fname[:-5]
            records = load_raw(lawd_cd, deal_ymd)
            if records is not None:
                upsert_region_month(conn, lawd_cd, deal_ymd, records)


# ---------------- state (backfill checkpoint) ----------------

def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"done": []}


def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=0)


def backfill_targets(today):
    """최근 BACKFILL_MONTHS개월 중, incremental이 커버하는 이번달/지난달을 제외한 (지역,월) 전체 목록."""
    skip = {month_str(today), month_str(add_months(today, -1))}
    months = []
    for i in range(2, BACKFILL_MONTHS):
        ym = month_str(add_months(today, -i))
        if ym not in skip:
            months.append(ym)
    targets = []
    for ym in months:
        for lawd_cd in REGIONS:
            targets.append((lawd_cd, ym))
    return targets


# ---------------- modes ----------------

def run_incremental(conn, today):
    months = [month_str(today), month_str(add_months(today, -1))]
    ok, failed = 0, 0
    for ym in months:
        for lawd_cd in REGIONS:
            try:
                records = fetch_region_month(lawd_cd, ym)
            except QuotaExceeded:
                print(f"[incremental] 트래픽 한도 도달, 중단 ({lawd_cd} {ym})")
                return ok, failed, True
            except Exception as e:
                print(f"[incremental] 실패 {lawd_cd} {ym}: {e}")
                failed += 1
                continue
            save_raw(lawd_cd, ym, records)
            upsert_region_month(conn, lawd_cd, ym, records)
            ok += 1
    return ok, failed, False


def run_backfill(conn, today, budget):
    state = load_state()
    done = set(tuple(x) for x in state["done"])
    targets = [t for t in backfill_targets(today) if t not in done]
    ok, failed = 0, 0
    quota_hit = False
    for lawd_cd, ym in targets[:budget]:
        try:
            records = fetch_region_month(lawd_cd, ym)
        except QuotaExceeded:
            print(f"[backfill] 트래픽 한도 도달, 중단 ({lawd_cd} {ym})")
            quota_hit = True
            break
        except Exception as e:
            print(f"[backfill] 실패 {lawd_cd} {ym}: {e}")
            failed += 1
            continue
        save_raw(lawd_cd, ym, records)
        upsert_region_month(conn, lawd_cd, ym, records)
        done.add((lawd_cd, ym))
        ok += 1
    state["done"] = sorted(list(done))
    state["updated_at"] = datetime.now(KST).isoformat()
    remaining = len(backfill_targets(today)) - len(done)
    state["remaining"] = remaining
    save_state(state)
    return ok, failed, remaining, quota_hit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["incremental", "backfill", "all"], default="all")
    args = parser.parse_args()

    if not MOLIT_KEY:
        raise SystemExit("MOLIT_KEY 환경변수가 설정되어 있지 않습니다.")

    today = datetime.now(KST).date().replace(day=1)
    conn = db_connect()
    rebuild_db_from_raw(conn)

    if args.mode in ("incremental", "all"):
        ok, failed, quota_hit = run_incremental(conn, today)
        print(f"incremental: 성공 {ok}, 실패 {failed}, 한도도달={quota_hit}")
        if args.mode == "all" and quota_hit:
            conn.close()
            return

    if args.mode in ("backfill", "all"):
        ok, failed, remaining, quota_hit = run_backfill(conn, today, BACKFILL_BUDGET)
        print(f"backfill: 성공 {ok}, 실패 {failed}, 남은조합 {remaining}, 한도도달={quota_hit}")

    conn.close()


if __name__ == "__main__":
    main()
