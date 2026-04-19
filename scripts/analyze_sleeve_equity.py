"""Sleeve 백테스트 자본 곡선 심층 분석.

logs/sleeve_final_equity.csv 를 읽어:
  - MDD (최대 낙폭) + 지속 기간 + 회복 기간
  - 연속 손실 구간 (낙폭 -5%, -10% 기준)
  - 월별 수익률 히스토그램
  - 최악/최고 주간·월간
  - 심리적 감당 지표 (Sortino, 하락 변동성)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def analyze_equity_curve(csv_path: str = "logs/sleeve_final_equity.csv") -> None:
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # equity curve 는 심볼별로 row 가 있으니 최신값만 뽑기 위해 timestamp 기준 최종값 사용
    # 각 timestamp 에 대해 마지막 row 의 total_equity 사용
    equity_series = df.groupby("timestamp")["total_equity"].last().sort_index()

    print(f"=== Sleeve 4년 연속 백테스트 자본 곡선 분석 ===")
    print(f"구간: {equity_series.index[0]} ~ {equity_series.index[-1]}")
    print(f"총 관측 시점: {len(equity_series)}")
    print(f"시작 자금: {equity_series.iloc[0]:,.2f}")
    print(f"최종 자금: {equity_series.iloc[-1]:,.2f}")
    print(f"총 수익률: {(equity_series.iloc[-1]/equity_series.iloc[0]-1)*100:+.2f}%")

    # ---------- MDD + 지속 기간 ----------
    cummax = equity_series.cummax()
    drawdown = (equity_series - cummax) / cummax * 100
    mdd = drawdown.min()
    mdd_idx = drawdown.idxmin()
    mdd_peak_idx = equity_series[: mdd_idx].idxmax()  # MDD 시작 (직전 peak)
    mdd_peak_eq = equity_series[mdd_peak_idx]
    mdd_trough_eq = equity_series[mdd_idx]

    # 회복 시점 탐색 (이전 peak 를 다시 넘는 시점)
    recovery_idx = None
    after_trough = equity_series[mdd_idx:]
    above_peak = after_trough[after_trough >= mdd_peak_eq]
    if not above_peak.empty:
        recovery_idx = above_peak.index[0]

    mdd_duration_days = (mdd_idx - mdd_peak_idx).days
    recovery_days = (recovery_idx - mdd_peak_idx).days if recovery_idx else None

    print(f"\n--- 최대 낙폭 (MDD) ---")
    print(f"MDD: {mdd:.2f}%")
    print(f"시작 시점 (peak): {mdd_peak_idx} @ {mdd_peak_eq:,.2f}")
    print(f"바닥 시점 (trough): {mdd_idx} @ {mdd_trough_eq:,.2f}")
    print(f"낙폭 구간 일수: {mdd_duration_days}일")
    if recovery_days:
        print(f"회복 시점: {recovery_idx} ({recovery_days}일 경과, peak 회복)")
    else:
        print(f"회복 안 됨 - 백테스트 종료까지 peak 미회복")

    # ---------- 낙폭 -5%, -10% 기준 구간 개수 ----------
    print(f"\n--- 낙폭 구간 분포 ---")
    in_dd = (drawdown < -0.01).astype(int)
    dd_groups = (in_dd != in_dd.shift()).cumsum()
    dd_runs = [
        (drawdown[dd_groups == g].min(), (drawdown[dd_groups == g].index[-1] - drawdown[dd_groups == g].index[0]).days)
        for g in dd_groups[in_dd == 1].unique()
    ]
    dd_5 = [r for r in dd_runs if r[0] <= -5]
    dd_10 = [r for r in dd_runs if r[0] <= -10]
    print(f"-5% 이상 낙폭 구간: {len(dd_5)}회")
    for d, days in dd_5[:5]:
        print(f"    {d:.2f}% × {days}일")
    print(f"-10% 이상 낙폭 구간: {len(dd_10)}회")

    # ---------- 월별 수익률 ----------
    print(f"\n--- 월별 수익률 ---")
    monthly = equity_series.resample("ME").last()
    monthly_returns = monthly.pct_change().dropna() * 100
    print(f"월 수: {len(monthly_returns)}")
    print(f"양수 월 비율: {(monthly_returns > 0).sum() / len(monthly_returns) * 100:.1f}%")
    print(f"평균 월 수익: {monthly_returns.mean():+.2f}%")
    print(f"월 수익 표준편차: {monthly_returns.std():.2f}%")
    print(f"최고 월: {monthly_returns.max():+.2f}% ({monthly_returns.idxmax().strftime('%Y-%m')})")
    print(f"최악 월: {monthly_returns.min():+.2f}% ({monthly_returns.idxmin().strftime('%Y-%m')})")

    # 월별 수익률 분포
    bins = [-50, -10, -5, -2, 0, 2, 5, 10, 50]
    hist, bin_edges = np.histogram(monthly_returns, bins=bins)
    print(f"\n월 수익 히스토그램:")
    for i in range(len(hist)):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        print(f"    [{lo:+3.0f}, {hi:+3.0f}]%: {hist[i]:>2}개월")

    # ---------- 심리적 감당 지표 ----------
    print(f"\n--- 심리적 감당 지표 ---")
    under_water_pct = (drawdown < -1).sum() / len(drawdown) * 100
    print(f"-1% 이상 낙폭 상태 시간 비율: {under_water_pct:.1f}%")
    print(f"(즉 백테스트 기간의 {under_water_pct:.0f}% 는 고점 대비 -1% 이상 낙폭 상태)")

    # 3개월 rolling return
    bars_per_3month = 90 * 24 // 4  # 4h 기준 90일
    if len(equity_series) > bars_per_3month:
        rolling_3m = equity_series.pct_change(bars_per_3month).dropna() * 100
        worst_3m = rolling_3m.min()
        worst_3m_end = rolling_3m.idxmin()
        print(f"최악 3개월 연속 수익: {worst_3m:+.2f}% (끝 시점: {worst_3m_end.strftime('%Y-%m-%d')})")

    # 6개월 rolling return
    bars_per_6month = 180 * 24 // 4
    if len(equity_series) > bars_per_6month:
        rolling_6m = equity_series.pct_change(bars_per_6month).dropna() * 100
        worst_6m = rolling_6m.min()
        worst_6m_end = rolling_6m.idxmin()
        print(f"최악 6개월 연속 수익: {worst_6m:+.2f}% (끝 시점: {worst_6m_end.strftime('%Y-%m-%d')})")

    # ---------- 실전 적용 기준선 ----------
    print(f"\n--- 실전 투자 판단 기준 ---")
    capital = 5_000_000
    print(f"500만원 기준 환산:")
    print(f"    기대 누적 수익 (4년): +{(equity_series.iloc[-1]/equity_series.iloc[0]-1)*100:.2f}% → {capital * (equity_series.iloc[-1]/equity_series.iloc[0]-1):+,.0f}원")
    print(f"    최대 낙폭 (MDD): {mdd:.2f}% → {capital * mdd/100:+,.0f}원 (피크 대비)")
    print(f"    일반 투자자 낙폭 허용 기준: -20% 이하 → {'✅ 통과' if mdd > -20 else '❌ 초과'}")


if __name__ == "__main__":
    analyze_equity_curve()
