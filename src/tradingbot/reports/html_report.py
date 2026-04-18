"""Plotly 기반 HTML 백테스트 리포트.

백테스트 결과 객체를 받아 다음을 포함한 단일 HTML 파일로 저장:
  - 핵심 지표 카드 (수익률, MDD, Sharpe, 승률)
  - 에쿼티 곡선 + 매수/매도 마커 + 드로우다운 오버레이
  - 월별 수익률 히트맵
  - 거래 내역 테이블
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from tradingbot.broker.base import OrderSide
from tradingbot.engine.backtester import BacktestResult


def _equity_and_drawdown_fig(result: BacktestResult) -> go.Figure:
    ec = result.equity_curve
    running_max = ec["equity"].cummax()
    drawdown = (ec["equity"] - running_max) / running_max * 100.0

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.7, 0.3],
        subplot_titles=("자산(Equity) 곡선", "드로우다운 (%)"),
    )

    fig.add_trace(
        go.Scatter(
            x=ec["timestamp"],
            y=ec["equity"],
            name="Equity",
            line={"color": "#2563eb", "width": 2},
        ),
        row=1,
        col=1,
    )

    # 매수/매도 마커
    buys = [t for t in result.trades if t.side == OrderSide.BUY]
    sells = [t for t in result.trades if t.side == OrderSide.SELL]
    if buys:
        fig.add_trace(
            go.Scatter(
                x=[t.timestamp for t in buys],
                y=[_equity_at(ec, t.timestamp) for t in buys],
                mode="markers",
                marker={"symbol": "triangle-up", "size": 12, "color": "#16a34a"},
                name="BUY",
            ),
            row=1,
            col=1,
        )
    if sells:
        fig.add_trace(
            go.Scatter(
                x=[t.timestamp for t in sells],
                y=[_equity_at(ec, t.timestamp) for t in sells],
                mode="markers",
                marker={"symbol": "triangle-down", "size": 12, "color": "#dc2626"},
                name="SELL",
            ),
            row=1,
            col=1,
        )

    fig.add_trace(
        go.Scatter(
            x=ec["timestamp"],
            y=drawdown,
            name="Drawdown",
            fill="tozeroy",
            line={"color": "#dc2626", "width": 1},
            fillcolor="rgba(220, 38, 38, 0.15)",
        ),
        row=2,
        col=1,
    )

    fig.update_layout(
        height=600,
        template="plotly_white",
        showlegend=True,
        margin={"l": 40, "r": 40, "t": 60, "b": 40},
    )
    fig.update_yaxes(title_text="자산", row=1, col=1)
    fig.update_yaxes(title_text="%", row=2, col=1)
    return fig


def _equity_at(ec: pd.DataFrame, ts) -> float:
    row = ec.loc[ec["timestamp"] == ts]
    if row.empty:
        # 시간이 정확히 일치하지 않으면 최근 값 사용
        return float(ec["equity"].iloc[-1])
    return float(row["equity"].iloc[0])


def _monthly_heatmap(result: BacktestResult) -> go.Figure:
    ec = result.equity_curve.copy()
    ec["timestamp"] = pd.to_datetime(ec["timestamp"], utc=True)
    ec["year"] = ec["timestamp"].dt.year
    ec["month"] = ec["timestamp"].dt.month
    monthly = ec.groupby(["year", "month"])["equity"].agg(["first", "last"])
    monthly["return_pct"] = (monthly["last"] / monthly["first"] - 1) * 100.0
    pivot = monthly["return_pct"].unstack(level="month")

    month_names = ["1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월", "12월"]
    pivot = pivot.reindex(columns=range(1, 13))
    fig = go.Figure(
        data=go.Heatmap(
            z=pivot.values,
            x=month_names,
            y=[str(y) for y in pivot.index],
            colorscale="RdYlGn",
            zmid=0,
            text=[[f"{v:+.1f}%" if pd.notna(v) else "" for v in row] for row in pivot.values],
            texttemplate="%{text}",
            hoverinfo="x+y+z",
            colorbar={"title": "%"},
        )
    )
    fig.update_layout(
        title="월별 수익률",
        template="plotly_white",
        height=max(200, 60 * max(1, len(pivot.index))),
        margin={"l": 40, "r": 40, "t": 60, "b": 40},
    )
    return fig


def _trades_table(result: BacktestResult) -> str:
    if not result.trades:
        return "<p>체결된 거래가 없습니다.</p>"
    rows = []
    for t in result.trades:
        rows.append(
            f"<tr>"
            f"<td>{t.timestamp.isoformat()}</td>"
            f"<td>{t.symbol}</td>"
            f"<td class='{'buy' if t.side == OrderSide.BUY else 'sell'}'>{t.side.value.upper()}</td>"
            f"<td>{t.amount:.6f}</td>"
            f"<td>{t.price:,.2f}</td>"
            f"<td>{t.fee:,.4f}</td>"
            f"</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>시간</th><th>심볼</th><th>방향</th><th>수량</th><th>체결가</th><th>수수료</th>"
        "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>"
    )


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>백테스트 리포트 — {symbol} {timeframe}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          max-width: 1200px; margin: 2rem auto; padding: 0 1rem; color: #111827; }}
  h1, h2 {{ color: #1f2937; }}
  .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
              gap: 1rem; margin: 1.5rem 0; }}
  .card {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px;
           padding: 1rem; }}
  .card .label {{ font-size: 0.85rem; color: #6b7280; text-transform: uppercase;
                  letter-spacing: 0.05em; }}
  .card .value {{ font-size: 1.5rem; font-weight: 600; margin-top: 0.25rem; }}
  .pos {{ color: #16a34a; }} .neg {{ color: #dc2626; }}
  table {{ width: 100%; border-collapse: collapse; margin: 1rem 0;
           font-size: 0.9rem; }}
  th, td {{ padding: 0.5rem 0.75rem; text-align: left;
            border-bottom: 1px solid #e5e7eb; }}
  th {{ background: #f3f4f6; font-weight: 600; }}
  td.buy {{ color: #16a34a; font-weight: 600; }}
  td.sell {{ color: #dc2626; font-weight: 600; }}
  footer {{ margin-top: 3rem; color: #6b7280; font-size: 0.85rem; text-align: center; }}
</style>
</head>
<body>
<h1>백테스트 리포트</h1>
<p><strong>{symbol}</strong> · {timeframe} · {start} ~ {end} · 전략 <code>{strategy}</code></p>

<div class="summary">
  <div class="card"><div class="label">총 수익률</div>
    <div class="value {ret_cls}">{return_pct:+.2f}%</div></div>
  <div class="card"><div class="label">최대 낙폭</div>
    <div class="value neg">-{mdd:.2f}%</div></div>
  <div class="card"><div class="label">Sharpe (연율)</div>
    <div class="value {sharpe_cls}">{sharpe:+.2f}</div></div>
  <div class="card"><div class="label">Sortino (연율)</div>
    <div class="value {sortino_cls}">{sortino:+.2f}</div></div>
  <div class="card"><div class="label">거래 횟수</div>
    <div class="value">{num_trades} ({win_rate:.1f}% 승률)</div></div>
  <div class="card"><div class="label">최종 자산</div>
    <div class="value">{ending_equity:,.2f}</div></div>
</div>

<h2>자산 곡선 & 드로우다운</h2>
{equity_html}

<h2>월별 수익률</h2>
{heatmap_html}

<h2>거래 내역</h2>
{trades_html}

<footer>
  Generated by tradingbot · {strategy} · {symbol} · {timeframe}
</footer>
</body>
</html>
"""


def render_html_report(result: BacktestResult, strategy_name: str, output: Path) -> Path:
    """백테스트 결과를 HTML 리포트 파일로 저장. 저장 경로 반환."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    equity_html = _equity_and_drawdown_fig(result).to_html(
        include_plotlyjs="cdn", full_html=False, config={"displaylogo": False}
    )
    heatmap_html = _monthly_heatmap(result).to_html(
        include_plotlyjs=False, full_html=False, config={"displaylogo": False}
    )

    def cls(val: float) -> str:
        return "pos" if val >= 0 else "neg"

    html = _HTML_TEMPLATE.format(
        symbol=result.symbol,
        timeframe=result.timeframe,
        start=result.start.date().isoformat(),
        end=result.end.date().isoformat(),
        strategy=strategy_name,
        return_pct=result.total_return_pct,
        ret_cls=cls(result.total_return_pct),
        mdd=result.max_drawdown_pct,
        sharpe=result.sharpe,
        sharpe_cls=cls(result.sharpe),
        sortino=result.sortino,
        sortino_cls=cls(result.sortino),
        num_trades=result.num_trades,
        win_rate=result.win_rate_pct,
        ending_equity=result.ending_equity,
        equity_html=equity_html,
        heatmap_html=heatmap_html,
        trades_html=_trades_table(result),
    )
    output.write_text(html, encoding="utf-8")
    return output
