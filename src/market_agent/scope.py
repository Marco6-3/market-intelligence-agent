from __future__ import annotations

from collections.abc import Iterable

from .models import StockItem

A_SHARE_OUT_OF_SCOPE_MESSAGE = (
    "A-share tickers are currently out of scope. Remove this ticker or implement a custom CN data source."
)
A_SHARE_SUFFIXES = (".SH", ".SZ")


def is_a_share_ticker(ticker: str) -> bool:
    return ticker.strip().upper().endswith(A_SHARE_SUFFIXES)


def is_out_of_scope_stock(stock: StockItem) -> bool:
    return stock.market == "CN" or is_a_share_ticker(stock.ticker)


def split_in_scope_stocks(stocks: Iterable[StockItem]) -> tuple[list[StockItem], list[StockItem]]:
    in_scope: list[StockItem] = []
    out_of_scope: list[StockItem] = []
    for stock in stocks:
        if is_out_of_scope_stock(stock):
            out_of_scope.append(stock)
        else:
            in_scope.append(stock)
    return in_scope, out_of_scope


def out_of_scope_warnings(stocks: Iterable[StockItem]) -> list[str]:
    return [
        f"{stock.ticker}: {A_SHARE_OUT_OF_SCOPE_MESSAGE}"
        for stock in stocks
        if is_out_of_scope_stock(stock)
    ]
