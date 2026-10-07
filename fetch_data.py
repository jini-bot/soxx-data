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
import json
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

# 국내 상장 ETF (참고/모니터링용 - SOXX·QQQ 백테스트와는 별도로 다룸)
# 야후 파이낸스 티커는 한국거래소(KRX) 상장 종목코드 뒤에 ".KS"를 붙인 형태입니다.
KR_TICKERS = {
    "381180": {"yahoo": "381180.KS", "name": "TIGER 미국필라델피아반도체나스닥"},
    "426030": {"yahoo": "426030.KS", "name": "TIME 미국나스닥100액티브"},
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

    n_missing_qqq = int(merged["qqq_close"].isna().sum())

    print("-" * 60)
    print(f"완료: {csv_out.name}, {json_out.name} 생성 ({len(merged)}행)")
    print(f"기간: {merged['date'].iloc[0]} ~ {merged['date'].iloc[-1]}")
    if n_missing_qqq > 0:
        print(f"[참고] QQQ 종가가 비어있는 날짜가 {n_missing_qqq}건 있습니다 "
              f"(거래정지/데이터 누락일 가능성).")
    print("이제 merged_data.json 파일을 backtest.html 에서 불러오면 됩니다.")
    print(f"생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    fetch_kr_etfs()


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


if __name__ == "__main__":
    main()
