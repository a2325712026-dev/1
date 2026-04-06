#!/usr/bin/env python3
"""MT5 止盈止损管理 GUI.

依赖:
    pip install MetaTrader5

功能:
- 连接/断开 MT5 终端
- 查看当前持仓
- TP 支持按价格或按金额计算
- SL 支持普通止损(按价格/按金额)和固定移动止损(按点数)
- 仅更新选中持仓或一键更新全部持仓
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Iterable, List, Optional

import MetaTrader5 as mt5


class MT5SLTPManagerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("MT5 止盈止损管理器")
        self.root.geometry("1120x700")

        self.connected = False
        self.positions_cache: List[dict] = []

        self._build_ui()

    def _build_ui(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.X)

        ttk.Label(top, text="MT5 路径(可选):").grid(row=0, column=0, sticky="w")
        self.path_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.path_var, width=60).grid(row=0, column=1, padx=5)

        ttk.Label(top, text="登录账号(可选):").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.login_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.login_var, width=20).grid(row=1, column=1, sticky="w", padx=5, pady=(6, 0))

        ttk.Label(top, text="密码:").grid(row=1, column=2, sticky="w", pady=(6, 0))
        self.password_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.password_var, show="*", width=20).grid(
            row=1, column=3, sticky="w", padx=5, pady=(6, 0)
        )

        ttk.Label(top, text="服务器:").grid(row=1, column=4, sticky="w", pady=(6, 0))
        self.server_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.server_var, width=20).grid(row=1, column=5, sticky="w", padx=5, pady=(6, 0))

        btns = ttk.Frame(top)
        btns.grid(row=0, column=6, rowspan=2, padx=(10, 0))
        ttk.Button(btns, text="连接", command=self.connect).pack(fill=tk.X)
        ttk.Button(btns, text="断开", command=self.disconnect).pack(fill=tk.X, pady=4)
        ttk.Button(btns, text="刷新持仓", command=self.refresh_positions).pack(fill=tk.X)

        cfg = ttk.LabelFrame(self.root, text="止盈止损设置", padding=10)
        cfg.pack(fill=tk.X, padx=10, pady=(0, 8))

        # TP 设置: 二选一(价格/金额)，且必填
        tp_frame = ttk.LabelFrame(cfg, text="止盈 TP（2 项可选，1 项必选）", padding=8)
        tp_frame.grid(row=0, column=0, columnspan=6, sticky="ew", pady=(0, 8))

        self.tp_mode_var = tk.StringVar(value="price")
        ttk.Radiobutton(tp_frame, text="按价格", value="price", variable=self.tp_mode_var, command=self._sync_input_states).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Radiobutton(tp_frame, text="按金额", value="money", variable=self.tp_mode_var, command=self._sync_input_states).grid(
            row=0, column=1, sticky="w", padx=(12, 0)
        )

        ttk.Label(tp_frame, text="TP 价格:").grid(row=1, column=0, sticky="e", pady=(6, 0))
        self.tp_price_var = tk.StringVar()
        self.tp_price_entry = ttk.Entry(tp_frame, textvariable=self.tp_price_var, width=18)
        self.tp_price_entry.grid(row=1, column=1, sticky="w", pady=(6, 0))

        ttk.Label(tp_frame, text="TP 金额:").grid(row=1, column=2, sticky="e", pady=(6, 0), padx=(12, 0))
        self.tp_money_var = tk.StringVar()
        self.tp_money_entry = ttk.Entry(tp_frame, textvariable=self.tp_money_var, width=18)
        self.tp_money_entry.grid(row=1, column=3, sticky="w", pady=(6, 0))

        # SL 设置: 普通止损/固定移动止损
        sl_frame = ttk.LabelFrame(cfg, text="止损 SL（3 项输入：普通 2 选 1 / 固定移动止损点数）", padding=8)
        sl_frame.grid(row=1, column=0, columnspan=6, sticky="ew", pady=(0, 8))

        self.sl_kind_var = tk.StringVar(value="normal")
        ttk.Radiobutton(
            sl_frame,
            text="普通止损",
            value="normal",
            variable=self.sl_kind_var,
            command=self._sync_input_states,
        ).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(
            sl_frame,
            text="固定移动止损",
            value="trailing",
            variable=self.sl_kind_var,
            command=self._sync_input_states,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0))

        self.sl_mode_var = tk.StringVar(value="price")
        ttk.Radiobutton(sl_frame, text="SL 按价格", value="price", variable=self.sl_mode_var, command=self._sync_input_states).grid(
            row=1, column=0, sticky="w", pady=(6, 0)
        )
        ttk.Radiobutton(sl_frame, text="SL 按金额", value="money", variable=self.sl_mode_var, command=self._sync_input_states).grid(
            row=1, column=1, sticky="w", pady=(6, 0), padx=(12, 0)
        )

        ttk.Label(sl_frame, text="SL 价格:").grid(row=2, column=0, sticky="e", pady=(6, 0))
        self.sl_price_var = tk.StringVar()
        self.sl_price_entry = ttk.Entry(sl_frame, textvariable=self.sl_price_var, width=18)
        self.sl_price_entry.grid(row=2, column=1, sticky="w", pady=(6, 0))

        ttk.Label(sl_frame, text="SL 金额:").grid(row=2, column=2, sticky="e", pady=(6, 0), padx=(12, 0))
        self.sl_money_var = tk.StringVar()
        self.sl_money_entry = ttk.Entry(sl_frame, textvariable=self.sl_money_var, width=18)
        self.sl_money_entry.grid(row=2, column=3, sticky="w", pady=(6, 0))

        ttk.Label(sl_frame, text="固定移动止损点数:").grid(row=3, column=0, sticky="e", pady=(6, 0))
        self.sl_trailing_points_var = tk.StringVar()
        self.sl_trailing_points_entry = ttk.Entry(sl_frame, textvariable=self.sl_trailing_points_var, width=18)
        self.sl_trailing_points_entry.grid(row=3, column=1, sticky="w", pady=(6, 0))

        ttk.Button(cfg, text="更新选中持仓", command=self.update_selected).grid(row=2, column=4, padx=12)
        ttk.Button(cfg, text="更新全部持仓", command=self.update_all).grid(row=2, column=5, padx=6)

        tips = (
            "TP 必须在【按价格/按金额】中选择一种并填写。\n"
            "SL 可切换【普通止损】或【固定移动止损】。普通止损需在【按价格/按金额】中二选一填写；"
            "固定移动止损需填写点数（每次点击更新时，按当前价重新计算并提交）。"
        )
        ttk.Label(cfg, text=tips, foreground="#555").grid(row=3, column=0, columnspan=6, sticky="w", pady=(6, 0))
        self._sync_input_states()

        table_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        table_frame.pack(fill=tk.BOTH, expand=True)

        columns = ("ticket", "symbol", "type", "volume", "price_open", "sl", "tp", "price_current", "profit")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=16)

        headers = {
            "ticket": "订单号",
            "symbol": "品种",
            "type": "方向",
            "volume": "手数",
            "price_open": "开仓价",
            "sl": "止损",
            "tp": "止盈",
            "price_current": "现价",
            "profit": "浮盈亏",
        }
        for c in columns:
            self.tree.heading(c, text=headers[c])
            self.tree.column(c, width=100, anchor="center")
        self.tree.column("symbol", width=120)
        self.tree.column("ticket", width=110)

        ybar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ybar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ybar.pack(side=tk.RIGHT, fill=tk.Y)

        self.status_var = tk.StringVar(value="未连接")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w").pack(fill=tk.X, side=tk.BOTTOM)

    def connect(self) -> None:
        path = self.path_var.get().strip() or None
        login_raw = self.login_var.get().strip()
        login = int(login_raw) if login_raw else None
        password = self.password_var.get().strip() or None
        server = self.server_var.get().strip() or None

        kwargs = {}
        if path:
            kwargs["path"] = path
        if login is not None:
            kwargs["login"] = login
        if password:
            kwargs["password"] = password
        if server:
            kwargs["server"] = server

        ok = mt5.initialize(**kwargs)
        if not ok:
            code, msg = mt5.last_error()
            messagebox.showerror("连接失败", f"初始化失败: {code} {msg}")
            self.connected = False
            self.status_var.set("连接失败")
            return

        account = mt5.account_info()
        self.connected = True
        if account:
            self.status_var.set(f"已连接: {account.login} | {account.server}")
        else:
            self.status_var.set("已连接")
        self.refresh_positions()

    def disconnect(self) -> None:
        if self.connected:
            mt5.shutdown()
        self.connected = False
        self.status_var.set("已断开")
        self.positions_cache = []
        self._render_positions([])

    def refresh_positions(self) -> None:
        if not self.connected:
            messagebox.showwarning("未连接", "请先连接 MT5")
            return

        positions = mt5.positions_get()
        if positions is None:
            code, msg = mt5.last_error()
            messagebox.showerror("读取失败", f"获取持仓失败: {code} {msg}")
            return

        rows = []
        for p in positions:
            rows.append(
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                    "volume": p.volume,
                    "price_open": p.price_open,
                    "sl": p.sl,
                    "tp": p.tp,
                    "price_current": p.price_current,
                    "profit": p.profit,
                }
            )
        self.positions_cache = rows
        self._render_positions(rows)
        self.status_var.set(f"已连接 | 持仓数: {len(rows)}")

    def _render_positions(self, rows: Iterable[dict]) -> None:
        for item in self.tree.get_children():
            self.tree.delete(item)

        for row in rows:
            self.tree.insert(
                "",
                tk.END,
                values=(
                    row["ticket"],
                    row["symbol"],
                    row["type"],
                    f"{row['volume']:.2f}",
                    f"{row['price_open']:.5f}",
                    f"{row['sl']:.5f}" if row["sl"] else "-",
                    f"{row['tp']:.5f}" if row["tp"] else "-",
                    f"{row['price_current']:.5f}",
                    f"{row['profit']:.2f}",
                ),
            )

    def _sync_input_states(self) -> None:
        tp_mode = self.tp_mode_var.get()
        self.tp_price_entry.configure(state=("normal" if tp_mode == "price" else "disabled"))
        self.tp_money_entry.configure(state=("normal" if tp_mode == "money" else "disabled"))

        sl_kind = self.sl_kind_var.get()
        sl_mode = self.sl_mode_var.get()
        normal_enabled = sl_kind == "normal"

        self.sl_price_entry.configure(state=("normal" if normal_enabled and sl_mode == "price" else "disabled"))
        self.sl_money_entry.configure(state=("normal" if normal_enabled and sl_mode == "money" else "disabled"))
        self.sl_trailing_points_entry.configure(state=("normal" if sl_kind == "trailing" else "disabled"))

    @staticmethod
    def _to_positive_float(value: str, field_name: str) -> float:
        v = float(value)
        if v <= 0:
            raise ValueError(f"{field_name} 必须大于 0")
        return v

    def _calc_price_from_money(self, position, money_amount: float, for_tp: bool, info) -> float:
        symbol = position.symbol
        digits = info.digits
        point = info.point
        if point <= 0:
            raise ValueError(f"{symbol} 点值无效")

        is_buy = position.type == mt5.POSITION_TYPE_BUY
        open_price = position.price_open
        volume = position.volume
        order_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL

        if for_tp:
            probe_close = open_price + point if is_buy else open_price - point
            direction = 1 if is_buy else -1
        else:
            probe_close = open_price - point if is_buy else open_price + point
            direction = -1 if is_buy else 1

        probe_profit = mt5.order_calc_profit(order_type, symbol, volume, open_price, probe_close)
        if probe_profit is None or probe_profit == 0:
            raise ValueError(f"{symbol} 无法按金额计算目标价格（请检查品种交易参数）")

        points_needed = money_amount / abs(probe_profit)
        target_price = open_price + direction * points_needed * point
        return round(target_price, digits)

    def _calc_prices(self, position) -> tuple[Optional[float], Optional[float]]:
        symbol = position.symbol
        info = mt5.symbol_info(symbol)
        if info is None:
            raise ValueError(f"无法读取品种信息: {symbol}")
        digits = info.digits

        # TP: 二选一必填
        tp_mode = self.tp_mode_var.get()
        tp_price: Optional[float]
        if tp_mode == "price":
            tp_text = self.tp_price_var.get().strip()
            if not tp_text:
                raise ValueError("TP 按价格模式下，TP 价格必填")
            tp_price = round(float(tp_text), digits)
        else:
            tp_money_text = self.tp_money_var.get().strip()
            if not tp_money_text:
                raise ValueError("TP 按金额模式下，TP 金额必填")
            tp_money = self._to_positive_float(tp_money_text, "TP 金额")
            tp_price = self._calc_price_from_money(position, tp_money, for_tp=True, info=info)

        # SL: 普通止损(价格/金额) 或 固定移动止损(点数)
        sl_kind = self.sl_kind_var.get()
        sl_price: Optional[float]
        if sl_kind == "normal":
            sl_mode = self.sl_mode_var.get()
            if sl_mode == "price":
                sl_text = self.sl_price_var.get().strip()
                if not sl_text:
                    raise ValueError("普通止损-按价格模式下，SL 价格必填")
                sl_price = round(float(sl_text), digits)
            else:
                sl_money_text = self.sl_money_var.get().strip()
                if not sl_money_text:
                    raise ValueError("普通止损-按金额模式下，SL 金额必填")
                sl_money = self._to_positive_float(sl_money_text, "SL 金额")
                sl_price = self._calc_price_from_money(position, sl_money, for_tp=False, info=info)
        else:
            trailing_text = self.sl_trailing_points_var.get().strip()
            if not trailing_text:
                raise ValueError("固定移动止损模式下，止损点数必填")
            trailing_points = self._to_positive_float(trailing_text, "固定移动止损点数")
            delta = trailing_points * info.point
            is_buy = position.type == mt5.POSITION_TYPE_BUY
            sl_price = position.price_current - delta if is_buy else position.price_current + delta
            sl_price = round(sl_price, digits)

        return sl_price, tp_price

    def _update_position(self, ticket: int) -> tuple[bool, str]:
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            return False, f"票号 {ticket} 持仓不存在"

        pos = positions[0]
        try:
            sl_price, tp_price = self._calc_prices(pos)
        except ValueError as e:
            return False, str(e)

        req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "symbol": pos.symbol,
            "sl": pos.sl if sl_price is None else sl_price,
            "tp": pos.tp if tp_price is None else tp_price,
            "comment": "SLTP Manager GUI",
        }

        result = mt5.order_send(req)
        if result is None:
            code, msg = mt5.last_error()
            return False, f"发送失败: {code} {msg}"

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return False, f"retcode={result.retcode}, comment={result.comment}"

        return True, "成功"

    def _selected_tickets(self) -> List[int]:
        selected = self.tree.selection()
        tickets = []
        for iid in selected:
            values = self.tree.item(iid, "values")
            if values:
                tickets.append(int(values[0]))
        return tickets

    def update_selected(self) -> None:
        if not self.connected:
            messagebox.showwarning("未连接", "请先连接 MT5")
            return

        tickets = self._selected_tickets()
        if not tickets:
            messagebox.showwarning("未选择", "请先在列表中选择持仓")
            return

        self._batch_update(tickets)

    def update_all(self) -> None:
        if not self.connected:
            messagebox.showwarning("未连接", "请先连接 MT5")
            return

        positions = mt5.positions_get()
        if not positions:
            messagebox.showinfo("提示", "当前没有持仓")
            return

        tickets = [int(p.ticket) for p in positions]
        self._batch_update(tickets)

    def _batch_update(self, tickets: List[int]) -> None:
        success = []
        failed = []

        for t in tickets:
            ok, msg = self._update_position(t)
            if ok:
                success.append(t)
            else:
                failed.append((t, msg))

        self.refresh_positions()

        parts = [f"成功: {len(success)}"]
        if failed:
            parts.append(f"失败: {len(failed)}")
            details = "\n".join(f"{t}: {m}" for t, m in failed[:10])
            messagebox.showwarning("更新完成", "\n".join(parts) + "\n\n" + details)
        else:
            messagebox.showinfo("更新完成", "\n".join(parts))


def main() -> None:
    root = tk.Tk()
    app = MT5SLTPManagerApp(root)

    def on_close() -> None:
        if app.connected:
            mt5.shutdown()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
