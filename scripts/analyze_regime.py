"""구간별 시장 regime 분석 스크립트.

각 기간의 buy-and-hold 수익률, 변동성, 최대 낙폭, 추세 지속성,
볼린저 밴드 돌파 빈도·후속 follow-through 등을 계산하여
볼린저 전략의 구간별 강약 원인을 진단.
"""

from __future__ import annotations

import pandas as pd
import numpy as np

from tradingbot.data.historical import fetch_historical
from tradingbot.exchange.ccxt_adapter import CCXTAdapter
from tradingbot.utils.indicators import bollinger_bands


def analyze_period(
    exchange: CCXTAdapter,
    symbol: str,
    start: str,
    end: str,
    timeframe: str = "4h",
) -> dict:
    """한 구간의 OHLCV 받아와 regime 지표 계산."""
    df = fetch_historical(exchange, symbol, timeframe, pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))
    if len(df) < 50:
        return {"error": f"데이터 부족: {len(df)}봉"}

    closes = df["close"].astype(float)
    returns = closes.pct_change().dropna()

    # 1. 순수익 (buy-and-hold)
    buy_hold_return = (closes.iloc[-1] / closes.iloc[0] - 1) * 100

    # 2. 변동성 (일간 std × sqrt(연)). 4h 는 연 2190개 봉 → annualization factor
    periods_per_year = 365 * 24 / 4 if timeframe == "4h" else 365
    volatility = returns.std() * np.sqrt(periods_per_year) * 100

    # 3. 최대 낙폭 (drawdown)
    cummax = closes.cummax()
    drawdown = (closes - cummax) / cummax
    max_dd = drawdown.min() * 100

    # 4. 추세 지속성 — 같은 방향 연속 일수 평균 / 최대
    signs = np.sign(returns)
    consecutive = []
    run = 1
    for i in range(1, len(signs)):
        if signs.iloc[i] == signs.iloc[i - 1] and signs.iloc[i] != 0:
            run += 1
        else:
            consecutive.append(run)
            run = 1
    consecutive.append(run)
    avg_run = float(np.mean(consecutive))
    max_run = int(np.max(consecutive))

    # 5. 볼린저 3.0 상단 돌파 빈도 + follow-through
    #    돌파 후 N봉 뒤 종가가 돌파 시점 종가보다 높으면 "추세 지속" 성공
    middle, upper, lower = bollinger_bands(closes, period=20, num_std=3.0)

    prev_close = closes.shift(1)
    breakouts_up = (closes > upper) & (prev_close <= upper.shift(1))

    n_breakouts = int(breakouts_up.sum())

    # 돌파 후 5봉 follow-through
    follow_through_5 = []
    for i in np.where(breakouts_up)[0]:
        if i + 5 < len(closes):
            ft = (closes.iloc[i + 5] / closes.iloc[i] - 1) * 100
            follow_through_5.append(ft)

    avg_follow_through = float(np.mean(follow_through_5)) if follow_through_5 else 0.0
    positive_follow = (
        sum(1 for x in follow_through_5 if x > 0) / len(follow_through_5) * 100
        if follow_through_5
        else 0.0
    )

    # 6. 하단 돌파 빈도 (손절 위험 빈도 근사)
    breakouts_down = (closes < lower) & (prev_close >= lower.shift(1))
    n_down_breakouts = int(breakouts_down.sum())

    return {
        "buy_hold_pct": round(buy_hold_return, 2),
        "volatility_annual_pct": round(volatility, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "avg_run": round(avg_run, 2),
        "max_run": max_run,
        "bollinger_upper_breakouts": n_breakouts,
        "avg_follow_through_5bars_pct": round(avg_follow_through, 2),
        "pct_breakouts_positive_follow": round(positive_follow, 1),
        "bollinger_lower_breakouts": n_down_breakouts,
    }


def main() -> None:
    exchange = CCXTAdapter(exchange_id="binance", api_key=None, api_secret=None, sandbox=False)

    periods = [
        ("22H1", "2022-01-01", "2022-07-01"),
        ("22H2", "2022-07-01", "2023-01-01"),
        ("23H1", "2023-01-01", "2023-07-01"),
        ("23H2", "2023-07-01", "2024-01-01"),
        ("24H1", "2024-01-01", "2024-07-01"),
        ("24H2", "2024-07-01", "2025-01-01"),
        ("25H1", "2025-01-01", "2025-07-01"),
        ("25H2", "2025-07-01", "2026-01-01"),
    ]
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    print(f"{'sym':10} {'pd':6} {'B&H':>7} {'Vol':>6} {'MDD':>7} {'Run':>5} {'BrkUp':>6} {'FT5':>7} {'+%':>6} {'BrkDn':>6}")
    for sym in symbols:
        for label, s, e in periods:
            try:
                r = analyze_period(exchange, sym, s, e)
            except Exception as exc:
                print(f"{sym:10} {label:6} ERROR: {exc}")
                continue
            if "error" in r:
                print(f"{sym:10} {label:6} {r['error']}")
                continue
            print(
                f"{sym:10} {label:6} "
                f"{r['buy_hold_pct']:+7.2f} "
                f"{r['volatility_annual_pct']:6.1f} "
                f"{r['max_drawdown_pct']:+7.2f} "
                f"{r['avg_run']:5.2f} "
                f"{r['bollinger_upper_breakouts']:6d} "
                f"{r['avg_follow_through_5bars_pct']:+7.2f} "
                f"{r['pct_breakouts_positive_follow']:6.1f} "
                f"{r['bollinger_lower_breakouts']:6d}"
            )
        print()


if __name__ == "__main__":
    main()
