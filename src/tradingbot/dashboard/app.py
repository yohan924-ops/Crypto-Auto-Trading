"""Streamlit 대시보드 앱.

logs/orders.jsonl 과 logs/ 내 CSV 를 읽어 실시간에 가깝게 상태를 시각화.
페이퍼/실전 Runner 가 background 에서 돌고 있을 때 이 대시보드를 띄워
진행 상황을 브라우저에서 모니터.

실행:
    streamlit run src/tradingbot/dashboard/app.py
또는:
    python -m tradingbot dashboard
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

LOG_DIR = Path("logs")
ORDERS_FILE = LOG_DIR / "orders.jsonl"


@st.cache_data(ttl=5)
def load_events() -> pd.DataFrame:
    if not ORDERS_FILE.exists():
        return pd.DataFrame()
    rows = []
    with open(ORDERS_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    df = pd.DataFrame(rows)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    return df


def _fills(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty or "event" not in events.columns:
        return pd.DataFrame()
    mask = events["event"].isin(["order_filled", "backtest_fill"])
    return events[mask].copy()


def _signals(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty or "event" not in events.columns:
        return pd.DataFrame()
    sig = events[events["event"] == "signal"].copy()
    if "type" in sig.columns:
        sig = sig[sig["type"] != "hold"]
    return sig


def _render_metrics(fills: pd.DataFrame) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 체결 수", len(fills))
    if fills.empty:
        col2.metric("매수", 0)
        col3.metric("매도", 0)
        col4.metric("총 수수료", "0.00")
        return
    buys = (fills["side"] == "buy").sum() if "side" in fills.columns else 0
    sells = (fills["side"] == "sell").sum() if "side" in fills.columns else 0
    fee_sum = fills["fee"].sum() if "fee" in fills.columns else 0.0
    col2.metric("매수", int(buys))
    col3.metric("매도", int(sells))
    col4.metric("총 수수료", f"{fee_sum:,.4f}")


def _render_fill_chart(fills: pd.DataFrame) -> None:
    if fills.empty:
        st.info("아직 체결 내역이 없습니다. paper/backtest/live 모드 실행 후 새로고침하세요.")
        return
    fig = go.Figure()
    for side, color in [("buy", "#16a34a"), ("sell", "#dc2626")]:
        subset = fills[fills["side"] == side]
        if subset.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=subset["timestamp"],
                y=subset["price"],
                mode="markers",
                marker={
                    "symbol": "triangle-up" if side == "buy" else "triangle-down",
                    "size": 12,
                    "color": color,
                },
                name=side.upper(),
                customdata=subset[["symbol", "amount"]].values if {"symbol", "amount"}.issubset(subset.columns) else None,
                hovertemplate=(
                    "%{x}<br>체결가=%{y:.2f}<br>수량=%{customdata[1]:.6f}<br>심볼=%{customdata[0]}"
                    if {"symbol", "amount"}.issubset(subset.columns)
                    else "%{x}<br>체결가=%{y:.2f}"
                ),
            )
        )
    fig.update_layout(
        template="plotly_white",
        height=450,
        margin={"l": 30, "r": 30, "t": 30, "b": 30},
        yaxis_title="체결가",
        xaxis_title="시간",
    )
    st.plotly_chart(fig, use_container_width=True)


def main() -> None:
    st.set_page_config(page_title="TradingBot Dashboard", layout="wide")
    st.title("📊 Crypto Auto-Trading Bot — 대시보드")
    st.caption(f"로그 파일: `{ORDERS_FILE.resolve()}`")

    auto_refresh = st.sidebar.toggle("자동 새로고침 (5초)", value=True)
    if auto_refresh:
        st.sidebar.caption("@st.cache_data TTL 로 5초마다 갱신")

    events = load_events()
    if events.empty:
        st.warning(
            "로그가 없습니다. `python -m tradingbot paper --max-bars 20` 같은 명령을 실행한 뒤 "
            "새로고침하세요."
        )
        return

    fills = _fills(events)
    signals = _signals(events)

    st.subheader("핵심 지표")
    _render_metrics(fills)

    st.subheader("체결 포인트")
    _render_fill_chart(fills)

    left, right = st.columns(2)
    with left:
        st.subheader("최근 체결 내역 (최대 20건)")
        if not fills.empty:
            display_cols = [c for c in ("timestamp", "symbol", "side", "amount", "price", "fee") if c in fills.columns]
            st.dataframe(
                fills[display_cols].tail(20).iloc[::-1],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write("없음")
    with right:
        st.subheader("최근 신호 (HOLD 제외)")
        if not signals.empty:
            display_cols = [c for c in ("timestamp", "symbol", "type", "price", "reason") if c in signals.columns]
            st.dataframe(
                signals[display_cols].tail(20).iloc[::-1],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.write("없음")

    st.caption("자동 새로고침이 꺼져있으면 브라우저 새로고침 또는 'R' 키로 갱신하세요.")


if __name__ == "__main__":
    main()
