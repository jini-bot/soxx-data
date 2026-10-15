# -*- coding: utf-8 -*-
"""
fetch_data.py
==============================================================
SOXX / QQQ 일별 시세 데이터를 API(yfinance)로 다운로드하는 PC 전용 스크립트.

- 2001-07-09 부터 오늘까지의 일별 OHLCV 데이터를 내려받습니다.
- 결과물:
    soxx_raw.csv       : SOXX 원본 데이터
    qqq_raw.csv        : QQQ 원본 데이터
    merged_data.csv     : 백테스트 프로그램(backtest.html)이 사용하는 병합 데이터 (CSV)
    merged_data.json    : 백테스트 프로그램(backtest.html)이 사용하는 병합 데이터 (JSON, 더 빠르게 로딩됨)
    kr_etf_data.json    : 국내 상장 ETF(TIGER필반/TIME나스닥100) 참고 데이터
    ref_index_data.json : SOX지수/VIX/미국10년물금리/WTI/달러인덱스/원달러환율/다우산업·운송지수/
                          S&P500/3개월물금리/하이일드채권ETF/투자등급채권ETF/장기국채ETF 참고·분석용 데이터
                          (전부 야후 파이낸스에서 받아오는 "대세하락 감지" 후보지표 포함)
    fred_data.json      : 세인트루이스 연준(FRED)에서 받아오는 거시경제 지표
                          (샴의 법칙, 선행경제지수, 장단기금리차, 하이일드 신용스프레드, 실업률)
                          ※ 이 스크립트를 PC에서 직접 실행하면 네트워크 환경에 따라 FRED 접속이
                          막혀있을 수 있습니다(사내망/방화벽 등). 그런 경우 이 단계만 건너뛰고
                          나머지 파일은 정상적으로 생성됩니다. GitHub Actions(자동 배치) 환경에서는
                          보통 제한 없이 접속됩니다.
    (위 4개 파일은 각각 최근 20개 데이터만 담은 _recent20.json 버전도 함께 생성됩니다)

사용법
------
1) (최초 1회) 필요한 패키지 설치
       pip install yfinance pandas --upgrade
   * 회사/개인 PC 환경에 따라 python 대신 python3, pip 대신 pip3 를 써야 할 수 있습니다.

2) 실행
       python fetch_data.py

3) 실행 후 같은 폴더에 생성된 merged_data.json 파일을
   backtest.html 에서 "데이터 불러오기" 버튼으로 불러오면 됩니다.

4) 이 스크립트는 인터넷 연결이 필요합니다(시세를 새로 받아올 때만).
   반대로 backtest.html 은 한 번 데이터를 불러온 뒤에는
   완전히 오프라인(인터넷 없이) PC/휴대폰에서 동작합니다.

주기적으로 최신 데이터를 반영하려면 이 스크립트를 다시 실행해서
merged_data.json 을 새로 만든 뒤, backtest.html 에서 다시 불러오면 됩니다.
==============================================================
"""

import sys
import io
import json
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

try:
    import pandas as pd
except ImportError:
    print("[오류] pandas 가 설치되어 있지 않습니다. 아래 명령으로 설치하세요:")
    print("       pip install pandas")
    sys.exit(1)

try:
    import yfinance as yf
except ImportError:
    print("[오류] yfinance 가 설치되어 있지 않습니다. 아래 명령으로 설치하세요:")
    print("       pip install yfinance")
    sys.exit(1)

START_DATE = "2001-07-09"
TICKERS = ["SOXX", "QQQ"]
OUT_DIR = Path(__file__).resolve().parent
RECENT_DAYS = 20  # 경량 갱신용 "최근 N일" 파일에 담을 거래일 수

# 국내 상장 ETF (참고/모니터링용 - SOXX·QQQ 백테스트와는 별도로 다룸)
# 야후 파이낸스 티커는 한국거래소(KRX) 상장 종목코드 뒤에 ".KS"를 붙인 형태입니다.
KR_TICKERS = {
    "381180": {"yahoo": "381180.KS", "name": "TIGER 미국필라델피아반도체나스닥"},
    "426030": {"yahoo": "426030.KS", "name": "TIME 미국나스닥100액티브"},
}

# 전략 분석/검증용 참고 지표 (SOXX/QQQ 백테스트·매매신호와는 완전히 분리되어 있으며 참고용입니다)
# - sox: 필라델피아 반도체지수. SOXX ETF(2001년 상장)보다 역사가 길어(1990년대부터)
#        닷컴버블 붕괴 등 과거 극단적 하락장까지 포함해 전략을 검증해볼 수 있습니다.
# - vix: VIX(변동성지수). 시장 공포심리 측정 - 매수/매도 타이밍 보조지표로 활용 가능.
# - tnx: 미국 10년물 국채금리. 반도체주는 금리 민감도가 높아 금리 레짐별 분석에 활용.
#        주의: 과거에는 야후의 ^TNX 값이 실제 금리(%)의 10배로 내려왔었지만(42.5=4.25%),
#        현재 yfinance는 이미 실제 %값(예: 4.25)을 그대로 줍니다. divide_by는 1로 둡니다.
#        (예전 코드에서 10으로 나누고 있었다면 실제값의 1/10로 잘못 저장되는 버그이니 주의)
# - wti:  WTI 원유 선물(연속물). 인플레이션/긴축 압력의 대리지표 성격.
# - dxy:  미국 달러인덱스(ICE). 달러 강세는 반도체 등 미국 수출기업 매출에 역풍으로 작용.
# - krw:  원달러환율. 국내 투자자 환노출 관점의 참고 지표.
# --- 아래는 "대세하락(기술주 국한이 아닌 시장 전체 하락장) 감지" 후보지표로 추가 ---
# - dji:  다우존스 산업평균지수. 전통적 다우이론(산업지수-운송지수 동반 신고점/신저점)에 사용.
# - djt:  다우존스 운송지수. dji와 짝을 이뤄 다우이론 확인(컨펌)에 사용.
# - gspc: S&P500 지수. 시장 전체의 대표적인 추세(50일선/200일선) 판단 기준.
# - irx:  13주(3개월) 미국 국채 금리. 장단기금리차(역전) 계산에서 "단기" 쪽 재료로 활용 가능
#         (다만 더 표준적인 10년-2년/10년-3개월 스프레드는 FRED에서 직접 받아오는 것이 더 정확 - 아래 FRED_SERIES 참고).
# - hyg:  하이일드(고수익) 회사채 ETF. 신용경색 신호(주가 대비 더 먼저 반응하는 경우가 있음) 참고용.
# - lqd:  투자등급 회사채 ETF. hyg와 비교해 신용스프레드 확대 여부를 가늠하는 참고용.
# - ief:  7-10년 만기 미국 국채 ETF. hyg/lqd와 비교할 때 "무위험금리" 대용으로 활용.
REF_INDICES = {
    "sox": {"yahoo": "^SOX", "name": "필라델피아 반도체지수", "start": "1993-01-01", "divide_by": 1},
    "vix": {"yahoo": "^VIX", "name": "VIX(변동성지수)", "start": "1990-01-01", "divide_by": 1},
    "tnx": {"yahoo": "^TNX", "name": "미국 10년물 국채금리(%)", "start": "1990-01-01", "divide_by": 1},
    "wti": {"yahoo": "CL=F", "name": "WTI 원유(배럴당 달러)", "start": "2000-01-01", "divide_by": 1},
    "dxy": {"yahoo": "DX-Y.NYB", "name": "미국 달러인덱스(DXY)", "start": "1990-01-01", "divide_by": 1},
    "krw": {"yahoo": "KRW=X", "name": "원달러환율(원/달러)", "start": "2000-01-01", "divide_by": 1},
    "dji": {"yahoo": "^DJI", "name": "다우존스 산업평균지수", "start": "1990-01-01", "divide_by": 1},
    "djt": {"yahoo": "^DJT", "name": "다우존스 운송지수", "start": "1990-01-01", "divide_by": 1},
    "gspc": {"yahoo": "^GSPC", "name": "S&P500 지수", "start": "1990-01-01", "divide_by": 1},
    "irx": {"yahoo": "^IRX", "name": "미국 13주(3개월) 국채금리(%)", "start": "1990-01-01", "divide_by": 1},
    "hyg": {"yahoo": "HYG", "name": "하이일드 회사채 ETF(HYG)", "start": "2007-01-01", "divide_by": 1},
    "lqd": {"yahoo": "LQD", "name": "투자등급 회사채 ETF(LQD)", "start": "2002-01-01", "divide_by": 1},
    "ief": {"yahoo": "IEF", "name": "7-10년 미국 국채 ETF(IEF)", "start": "2002-01-01", "divide_by": 1},
}

# FRED(세인트루이스 연방준비은행)에서 직접 받아오는 거시경제 지표.
# API 키 없이 공개 CSV 엔드포인트(fredgraph.csv)로 받아올 수 있습니다.
# 이 사이트 접속은 일반 PC/사내망에서는 막혀있을 수 있지만, GitHub Actions 환경에서는
# 보통 제한 없이 접속됩니다(이 저장소의 자동 배치 워크플로우가 이 함수를 매번 실행합니다).
# - sahm:      샴의 법칙(Sahm Rule) 실시간 경기침체 지표. 0.5%p 이상이면 경기침체 진입으로 판단하는
#              대표적인 "데이터 기반" 침체 판별 공식(월간 발표, 실업률로부터 계산됨).
# - leading:   세인트루이스 연은의 "Leading Index"(USSLIND). 콘퍼런스보드의 유료 LEI(경기선행지수)를
#              대체할 수 있는 무료 대안 지표(월간, 주별 선행지수를 합산).
# - t10y2y:    10년물-2년물 국채금리차. 가장 널리 쓰이는 장단기금리역전(경기침체 선행신호) 지표.
# - t10y3m:    10년물-3개월물 국채금리차. 연준이 자체 연구에서 더 선호한다고 밝힌 대안 스프레드.
# - hyspread:  ICE BofA 미국 하이일드 신용스프레드(OAS). HYG/LQD/IEF ETF가격비로 "근사"하는 것보다
#              훨씬 정확한 실제 신용스프레드 수치.
# - unrate:    미국 실업률(월간). 샴의 법칙 계산의 원재료이자 그 자체로도 경기 참고지표.
FRED_SERIES = {
    "sahm": {"id": "SAHMREALTIME", "name": "샴의 법칙(실시간 경기침체지표)"},
    "leading": {"id": "USSLIND", "name": "세인트루이스 연은 선행지수(LEI 무료 대체)"},
    "t10y2y": {"id": "T10Y2Y", "name": "장단기금리차(10년-2년)"},
    "t10y3m": {"id": "T10Y3M", "name": "장단기금리차(10년-3개월)"},
    "hyspread": {"id": "BAMLH0A0HYM2", "name": "하이일드 신용스프레드(ICE BofA OAS)"},
    "unrate": {"id": "UNRATE", "name": "미국 실업률(%)"},
}


def _flatten_columns(df):
    """yfinance 버전에 따라 MultiIndex 컬럼이 나올 수 있어 평탄화 처리."""
    new_cols = []
    for c in df.columns:
        if isinstance(c, tuple):
            new_cols.append(c[0])
        else:
            new_cols.append(c)
    df.columns = new_cols
    return df


def fetch_ticker(ticker: str) -> pd.DataFrame:
    print(f"[다운로드 중] {ticker} ... (기간: {START_DATE} ~ 오늘)")
    df = yf.download(
        ticker,
        start=START_DATE,
        auto_adjust=False,   # 원본 종가(Close) 유지. 배당/분할 보정은 Adj Close 참고용으로만 사용
        progress=False,
        threads=True,
    )
    if df is None or df.empty:
        raise RuntimeError(
            f"{ticker} 데이터를 가져오지 못했습니다. "
            f"인터넷 연결 또는 티커명을 확인해주세요."
        )
    df = df.reset_index()
    df = _flatten_columns(df)
    # 컬럼명 정리 (Date, Open, High, Low, Close, Adj Close, Volume)
    df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
    return df


def main():
    print("=" * 60)
    print(" SOXX / QQQ 데이터 다운로드")
    print("=" * 60)

    data = {}
    for t in TICKERS:
        df = fetch_ticker(t)
        csv_path = OUT_DIR / f"{t.lower()}_raw.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(
            f"  -> 저장됨: {csv_path.name}  "
            f"({len(df)}행, {df['Date'].iloc[0]} ~ {df['Date'].iloc[-1]})"
        )
        data[t] = df.set_index("Date")

    soxx = data["SOXX"]
    qqq = data["QQQ"]

    # 두 종목을 날짜 기준으로 병합 (SOXX 거래일 기준, QQQ 값을 매칭)
    merged = pd.DataFrame(index=soxx.index)
    merged["soxx_open"] = soxx["Open"]
    merged["soxx_high"] = soxx["High"]
    merged["soxx_low"] = soxx["Low"]
    merged["soxx_close"] = soxx["Close"]
    merged["soxx_volume"] = soxx["Volume"]
    merged["qqq_close"] = qqq["Close"].reindex(soxx.index)

    merged = merged.dropna(subset=["soxx_close"])
    merged = merged.sort_index()
    merged.index.name = "date"
    merged = merged.reset_index()

    # 숫자형 정리
    for col in ["soxx_open", "soxx_high", "soxx_low", "soxx_close", "qqq_close"]:
        merged[col] = merged[col].astype(float).round(4)
    merged["soxx_volume"] = merged["soxx_volume"].fillna(0).astype("int64")

    csv_out = OUT_DIR / "merged_data.csv"
    merged.to_csv(csv_out, index=False, encoding="utf-8-sig")

    json_out = OUT_DIR / "merged_data.json"
    records = merged.to_dict(orient="records")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False)

    # 최근 N일치만 담은 경량 파일 (웹앱에서 매번 전체(2001년~)를 받지 않고
    # 가벼운 갱신만 할 수 있도록 함 - GitHub Actions 자동 갱신용)
    recent_json_out = OUT_DIR / "merged_data_recent20.json"
    recent_records = records[-RECENT_DAYS:]
    with open(recent_json_out, "w", encoding="utf-8") as f:
        json.dump(recent_records, f, ensure_ascii=False)

    n_missing_qqq = int(merged["qqq_close"].isna().sum())

    print("-" * 60)
    print(f"완료: {csv_out.name}, {json_out.name} 생성 ({len(merged)}행)")
    print(f"완료: {recent_json_out.name} 생성 (최근 {len(recent_records)}행)")
    print(f"기간: {merged['date'].iloc[0]} ~ {merged['date'].iloc[-1]}")
    if n_missing_qqq > 0:
        print(f"[참고] QQQ 종가가 비어있는 날짜가 {n_missing_qqq}건 있습니다 "
              f"(거래정지/데이터 누락일 가능성).")
    print("이제 merged_data.json 파일을 backtest.html 에서 불러오면 됩니다.")
    print(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    fetch_kr_etfs()
    fetch_reference_indices()
    fetch_fred_series()


def fetch_and_merge_soxx_per(existing_out_path):
    """SOXX의 야후 파이낸스 trailing PER(주가수익비율, Ticker.info의 trailingPE)을
    가져와 ref_index_data.json 안에 "soxxper" 코드로 함께 저장합니다.

    다른 참고지표(REF_INDICES)와 달리 이 지표는 "과거 날짜별 이력을 다시 받아올 방법이
    없습니다"(야후를 포함해 어떤 무료/유료 소스도 ETF의 과거 특정일 PER을 제공하지 않음).
    그래서 매번 전체를 새로 내려받는 대신, 기존 ref_index_data.json에 이미 쌓여있던
    "soxxper" 이력을 먼저 읽어온 뒤, "이 스크립트를 실행한 시점의 PER 값 1개"만 오늘
    날짜로 추가(merge)합니다. 같은 날 여러 번 실행하면 그날 값만 최신값으로 덮어쓰고,
    그 이전 날짜들의 값은 그대로 보존됩니다. 이렇게 스크립트를 실행할 때마다 조금씩
    쌓여서, 시간이 지나면 점점 더 긴 이력이 됩니다(선행PER은 ETF 단위로는 어떤 곳에도
    존재하지 않는 지표라 수집하지 않습니다).
    """
    existing_rows = []
    if existing_out_path.exists():
        try:
            with open(existing_out_path, "r", encoding="utf-8") as f:
                prev = json.load(f)
            prev_entry = prev.get("soxxper")
            if prev_entry and isinstance(prev_entry.get("rows"), list):
                existing_rows = prev_entry["rows"]
        except Exception as e:
            print(f"  -> [경고] 기존 SOXX PER 이력 읽기 실패: {e} (새로 시작합니다)")
            existing_rows = []

    name = "SOXX PER(주가수익비율, 야후 trailing 12개월 기준·참고용 누적스냅샷)"
    try:
        print(f"[다운로드 중] SOXX PER(주가수익비율, 야후) ... (참고용 스냅샷 1개, 기존 {len(existing_rows)}일치에 추가)")
        info = yf.Ticker("SOXX").info
        per = info.get("trailingPE")
        if per is None:
            print("  -> [경고] 야후에서 SOXX trailingPE 값을 받지 못했습니다 (건너뜀, 기존 이력은 보존).")
            return {"name": name, "yahoo_ticker": "SOXX", "rows": existing_rows} if existing_rows else None

        today = datetime.now().strftime("%Y-%m-%d")
        by_date = {r["date"]: r["close"] for r in existing_rows}
        by_date[today] = round(float(per), 2)  # 오늘 값은 최신으로 덮어씀, 과거 값은 그대로 유지
        merged_rows = [{"date": d, "close": v} for d, v in sorted(by_date.items())]
        print(f"  -> SOXX PER {merged_rows[-1]['close']}배 ({today} 기준) 추가 저장 (누적 {len(merged_rows)}일치)")
        return {"name": name, "yahoo_ticker": "SOXX", "rows": merged_rows}
    except Exception as e:
        print(f"  -> [경고] SOXX PER 다운로드 중 오류 발생: {e} (건너뜀, 기존 이력은 보존).")
        return {"name": name, "yahoo_ticker": "SOXX", "rows": existing_rows} if existing_rows else None


def fetch_reference_indices():
    """SOX지수/VIX/미국10년물금리 등을 참고/분석용으로 한 파일(ref_index_data.json)에
    함께 저장합니다. SOXX/QQQ 백테스트 데이터와는 완전히 분리되어 있으며,
    이 단계가 실패해도(또는 일부 지표만 실패해도) 위 merged_data.json / kr_etf_data.json
    생성에는 영향이 없습니다. 지표 하나가 실패해도 나머지는 계속 받아옵니다.
    SOXX PER(주가수익비율)도 "soxxper" 코드로 이 파일에 함께 저장되는데, 이 지표만은
    과거 이력을 다시 받아올 수 없어 매번 전체를 새로 받는 대신 기존 값을 보존하며
    누적합니다(자세한 내용은 fetch_and_merge_soxx_per 참고)."""
    print("-" * 60)
    print(" 참고 지표(SOX지수/VIX/미국10년물금리/SOXX PER 등) 다운로드 (참고/분석용)")
    print("-" * 60)

    out_path = OUT_DIR / "ref_index_data.json"
    result = {}
    for code, meta in REF_INDICES.items():
        yahoo_ticker = meta["yahoo"]
        name = meta["name"]
        start = meta["start"]
        divide_by = meta.get("divide_by", 1)
        try:
            print(f"[다운로드 중] {name} ({yahoo_ticker}) ... (기간: {start} ~ 오늘)")
            df = yf.download(
                yahoo_ticker,
                start=start,
                auto_adjust=False,
                progress=False,
                threads=True,
            )
            if df is None or df.empty:
                print(f"  -> [경고] {name} 데이터를 가져오지 못했습니다 (건너뜀).")
                continue
            df = df.reset_index()
            df = _flatten_columns(df)
            df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
            df = df.dropna(subset=["Close"])
            df = df.sort_values("Date")

            csv_path = OUT_DIR / f"ref_{code}_raw.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")

            rows = [
                {"date": d, "close": round(float(c) / divide_by, 4)}
                for d, c in zip(df["Date"], df["Close"])
            ]
            result[code] = {"name": name, "yahoo_ticker": yahoo_ticker, "rows": rows}
            print(f"  -> 저장됨: {csv_path.name} ({len(rows)}행, {rows[0]['date']} ~ {rows[-1]['date']})")
        except Exception as e:
            print(f"  -> [경고] {name} 다운로드 중 오류 발생: {e} (건너뜀).")
            continue

    per_entry = fetch_and_merge_soxx_per(out_path)
    if per_entry:
        result["soxxper"] = per_entry

    if not result:
        print("[경고] 참고 지표를 하나도 받아오지 못했습니다. ref_index_data.json을 생성하지 않습니다.")
        return

    out_path = OUT_DIR / "ref_index_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"완료: {out_path.name} 생성됨 ({', '.join(result.keys())})")

    recent_result = {
        code: {"name": info["name"], "yahoo_ticker": info["yahoo_ticker"], "rows": info["rows"][-RECENT_DAYS:]}
        for code, info in result.items()
    }
    recent_out_path = OUT_DIR / "ref_index_data_recent20.json"
    with open(recent_out_path, "w", encoding="utf-8") as f:
        json.dump(recent_result, f, ensure_ascii=False)
    print(f"완료: {recent_out_path.name} 생성됨 (최근 {RECENT_DAYS}일)")


def fetch_fred_series():
    """FRED(세인트루이스 연은)에서 샴의 법칙/선행지수/장단기금리차/신용스프레드/실업률을
    API 키 없이 공개 CSV 엔드포인트로 받아와 fred_data.json에 저장합니다.
    SOXX/QQQ 백테스트 데이터와는 완전히 분리되어 있으며, 이 단계 전체(또는 지표 일부)가
    실패해도 다른 파일 생성에는 영향이 없습니다. 일반 PC/사내망에서는 FRED 접속이
    막혀있을 수 있으나(방화벽 등), GitHub Actions 환경에서는 보통 제한이 없습니다."""
    print("-" * 60)
    print(" FRED 거시경제 지표 다운로드 (참고/분석용)")
    print("-" * 60)

    result = {}
    for code, meta in FRED_SERIES.items():
        series_id = meta["id"]
        name = meta["name"]
        # cosd(관측 시작일)를 명시하지 않으면 일부 시리즈는 FRED가 기본 그래프 범위(최근 몇 년치)만
        # 내려주는 경우가 있어, 가능한 가장 이른 날짜(1950-01-01)를 명시해 전체 역사를 요청합니다.
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd=1950-01-01"
        try:
            print(f"[다운로드 중] {name} ({series_id}) ...")
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (compatible; soxx-tool-fetch/1.0)"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")

            df = pd.read_csv(io.StringIO(raw))
            # fredgraph.csv는 보통 "DATE,<series_id>" 두 컬럼으로 내려옵니다.
            date_col = df.columns[0]
            value_col = df.columns[1] if len(df.columns) > 1 else series_id
            df = df.rename(columns={date_col: "Date", value_col: "Value"})
            df["Value"] = pd.to_numeric(df["Value"], errors="coerce")  # 결측치는 "." 로 내려옴
            df = df.dropna(subset=["Value"])
            df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
            df = df.sort_values("Date")

            if df.empty:
                print(f"  -> [경고] {name} 데이터가 비어있습니다 (건너뜀).")
                continue

            csv_path = OUT_DIR / f"fred_{code}_raw.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")

            rows = [
                {"date": d, "value": round(float(v), 6)}
                for d, v in zip(df["Date"], df["Value"])
            ]
            result[code] = {"name": name, "fred_id": series_id, "rows": rows}
            print(f"  -> 저장됨: {csv_path.name} ({len(rows)}행, {rows[0]['date']} ~ {rows[-1]['date']})")
        except Exception as e:
            print(f"  -> [경고] {name} 다운로드 중 오류 발생: {e} (건너뜀). "
                  f"(사내망/방화벽 등으로 FRED 접속이 막혀있을 수 있습니다)")
            continue

    if not result:
        print("[경고] FRED 지표를 하나도 받아오지 못했습니다. fred_data.json을 생성하지 않습니다.")
        print("       (GitHub Actions 환경이 아니라면 정상일 수 있습니다 - 접속 제한 가능성)")
        return

    out_path = OUT_DIR / "fred_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"완료: {out_path.name} 생성됨 ({', '.join(result.keys())})")

    recent_result = {
        code: {"name": info["name"], "fred_id": info["fred_id"], "rows": info["rows"][-RECENT_DAYS:]}
        for code, info in result.items()
    }
    recent_out_path = OUT_DIR / "fred_data_recent20.json"
    with open(recent_out_path, "w", encoding="utf-8") as f:
        json.dump(recent_result, f, ensure_ascii=False)
    print(f"완료: {recent_out_path.name} 생성됨 (최근 {RECENT_DAYS}개)")


def fetch_kr_etfs():
    """국내 상장 ETF(TIGER 필라델피아반도체나스닥, TIME 나스닥100액티브)를
    참고/모니터링용으로 별도 파일(kr_etf_data.json)에 저장합니다.
    SOXX/QQQ 백테스트 데이터와는 완전히 분리되어 있으며,
    이 단계가 실패해도 위 merged_data.json 생성에는 영향이 없습니다."""
    print("-" * 60)
    print(" 국내 상장 ETF 다운로드 (참고/모니터링용)")
    print("-" * 60)

    result = {}
    for code, meta in KR_TICKERS.items():
        yahoo_ticker = meta["yahoo"]
        name = meta["name"]
        try:
            print(f"[다운로드 중] {name} ({yahoo_ticker}) ...")
            df = yf.download(
                yahoo_ticker,
                start=START_DATE,
                auto_adjust=False,
                progress=False,
                threads=True,
            )
            if df is None or df.empty:
                print(f"  -> [경고] {name} 데이터를 가져오지 못했습니다 (건너뜀).")
                continue
            df = df.reset_index()
            df = _flatten_columns(df)
            df["Date"] = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d")
            df = df.dropna(subset=["Close"])
            df = df.sort_values("Date")

            csv_path = OUT_DIR / f"kr_{code}_raw.csv"
            df.to_csv(csv_path, index=False, encoding="utf-8-sig")

            rows = [
                {"date": d, "close": round(float(c), 2)}
                for d, c in zip(df["Date"], df["Close"])
            ]
            result[code] = {"name": name, "yahoo_ticker": yahoo_ticker, "rows": rows}
            print(f"  -> 저장됨: {csv_path.name} ({len(rows)}행, {rows[0]['date']} ~ {rows[-1]['date']})")
        except Exception as e:
            print(f"  -> [경고] {name} 다운로드 중 오류 발생: {e} (건너뜀).")
            continue

    if not result:
        print("[경고] 국내 ETF 데이터를 하나도 받아오지 못했습니다. kr_etf_data.json을 생성하지 않습니다.")
        return

    out_path = OUT_DIR / "kr_etf_data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    print(f"완료: {out_path.name} 생성됨 ({', '.join(result.keys())})")
    print("이 파일을 backtest.html의 \"데이터\" 탭 > \"국내 상장 ETF 불러오기\"에서 불러오면 됩니다.")

    # 최근 N일치만 담은 경량 파일 (웹앱 자동/URL 갱신용)
    result_recent20 = {
        code: {
            "name": info["name"],
            "yahoo_ticker": info["yahoo_ticker"],
            "rows": info["rows"][-RECENT_DAYS:],
        }
        for code, info in result.items()
    }
    recent_out_path = OUT_DIR / "kr_etf_data_recent20.json"
    with open(recent_out_path, "w", encoding="utf-8") as f:
        json.dump(result_recent20, f, ensure_ascii=False)
    print(f"완료: {recent_out_path.name} 생성됨 (최근 {RECENT_DAYS}일)")


if __name__ == "__main__":
    main()
