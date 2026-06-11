#!/usr/bin/env python3
"""BNB HACK — Multi-Strategy Backtest Engine.

Tests SMA trend, RSI momentum, Bollinger, MACD strategies on BNB data.
Finds what's actually profitable for the 6-day competition window.

Usage:
    python -m backend.research.bnb_hack_backtest                          # All strategies
    python -m backend.research.bnb_hack_backtest --strategy sma_trend    # Specific
"""

import argparse, asyncio, json, math, sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import *

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

BINANCE = "https://api.binance.com/api/v3"
INIT_CAP = 34.0

class Strategy(str, Enum):
    SMA_TREND = "sma_trend"
    RSI_MOM = "rsi_momentum"
    BOLL = "bollinger"
    MACD = "macd"

@dataclass
class Trade:
    entry: datetime; exit: datetime
    entry_px: float; exit_px: float
    pnl_pct: float; pnl_usdc: float; reason: str

@dataclass
class Result:
    name: str; params: dict
    ret_pct: float; ret_usdc: float; wr: float; n: int; w: int; l: int
    dd: float; sharpe: float; pf: float
    avg_w: float; avg_l: float; max_w: float; max_l: float
    hold_m: float; trades: list[Trade]; eq: list[float]

# ── Data ──

async def fetch(interval: str, months: float) -> list[list]:
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    start = now - int(months * 30 * 24 * 3600 * 1000)
    all_k, cs = [], start
    while cs < now:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.get(f"{BINANCE}/klines", params=dict(symbol="BNBUSDT", interval=interval, limit=1000, startTime=cs))
            r.raise_for_status()
            k = r.json()
        if not k: break
        all_k.extend(k); cs = k[-1][0] + 1
        if len(k) < 100: break
        await asyncio.sleep(0.05)
    return all_k

def series(k: list[list]):
    c = [float(x[4]) for x in k]; h = [float(x[2]) for x in k]
    l = [float(x[3]) for x in k]; v = [float(x[5]) for x in k]
    t = [datetime.fromtimestamp(x[0]/1000, tz=timezone.utc) for x in k]
    return c, h, l, v, t

# ── Indicators ──

from backend.signals.technical import compute_sma_series as sma_s, compute_rsi_series as rsi_s

def ema_s(c: list[float], p: int):
    k = 2/(p+1); out = [c[0]]
    for i in range(1, len(c)): out.append(c[i]*k + out[-1]*(1-k))
    return out

def macd_s(c: list[float]):
    e12, e26 = ema_s(c,12), ema_s(c,26)
    macd = [a-b for a,b in zip(e12,e26)]
    sig = ema_s(macd,9)
    hist = [a-b for a,b in zip(macd,sig)]
    return macd, sig, hist

def bb_s(c: list[float], p=20, s=2.0):
    mid = sma_s(c, p); up, lo = [], []
    for i in range(len(c)):
        if i < p-1: up.append(0); lo.append(0)
        else:
            w = c[i+1-p:i+1]; sd = math.sqrt(sum((x-mid[i])**2 for x in w)/p)
            up.append(mid[i]+s*sd); lo.append(mid[i]-s*sd)
    return up, mid, lo

# ── Backtest ──

def bt(k: list[list], s: Strategy, p: dict) -> Result:
    c, _, _, _, t = series(k)
    warmup, fee = 60, 0.003
    rsi = rsi_s(c, p.get("rsi_p", 14))
    sf = sma_s(c, p.get("sf", 10))
    ss = sma_s(c, p.get("ss", 30))
    bb_up, bb_mid, bb_lo = bb_s(c, p.get("bb_p", 20), p.get("bb_s", 2.0))
    macd, macd_sig, macd_h = macd_s(c)

    if len(c) < warmup+10: return _empty(s.value, p)

    cap = peak = INIT_CAP; in_pos = False
    ep = 0.0; et = None; e_usdc = 0.0; qty = 0.0
    trades: list[Trade] = []; eq = [INIT_CAP]; max_dd = 0.0
    sl = p.get("sl", 0.03); tp = p.get("tp", 0.05)
    pos_pct = p.get("pos", 0.5)

    for i in range(warmup, len(c)):
        px = c[i]

        if in_pos:
            pnl = (px-ep)/ep; exit = False; reason = ""
            if pnl <= -sl: reason = "sl"; exit = True
            elif pnl >= tp: reason = "tp"; exit = True
            elif s == Strategy.SMA_TREND and sf[i] < ss[i] and sf[i-1] >= ss[i-1]:
                reason = "death_x"; exit = True
            elif s == Strategy.RSI_MOM:
                mode = p.get("entry_mode", ">50")
                if mode == ">50" and rsi[i] < 50 and rsi[i-1] >= 50:
                    reason = "rsi_below50"; exit = True
                elif mode == ">30" and rsi[i] < 50 and rsi[i-1] >= 50:
                    reason = "rsi_below50"; exit = True
            elif s == Strategy.BOLL and px >= bb_mid[i]:
                reason = "bb_mid"; exit = True
            elif s == Strategy.MACD and macd_h[i] < 0 and macd_h[i-1] >= 0:
                reason = "macd_sell"; exit = True

            if exit:
                ev = qty*px*(1-fee); pnl_usdc = ev-e_usdc; pnl_p = (px-ep)/ep*100
                cap = cap + ev; in_pos = False
                trades.append(Trade(et or t[i], t[i], ep, px, pnl_p, pnl_usdc, reason))

        if not in_pos and cap > 1:
            signal = False
            if s == Strategy.SMA_TREND and sf[i] > ss[i] and sf[i-1] <= ss[i-1]:
                signal = True
            elif s == Strategy.RSI_MOM:
                mode = p.get("entry_mode", ">50")
                if mode == ">50" and rsi[i] > 50 and rsi[i-1] <= 50:
                    signal = True
                elif mode == ">30" and rsi[i] > 30 and rsi[i-1] <= 30:
                    signal = True
            elif s == Strategy.BOLL and bb_lo[i] > 0 and px <= bb_lo[i]:
                signal = True
            elif s == Strategy.MACD and macd_h[i] > 0 and macd_h[i-1] <= 0:
                signal = True

            if signal:
                sz = cap*pos_pct*(1-fee)
                if sz >= 1:
                    ep = px; et = t[i]; e_usdc = sz
                    qty = sz/px; cap -= sz; in_pos = True

        eq_val = cap + (qty*c[i]*(1-fee) if in_pos else 0)
        eq.append(eq_val)
        if eq_val > peak: peak = eq_val
        dd = (peak-eq_val)/peak*100
        if dd > max_dd: max_dd = dd

    if in_pos:
        ev = qty*c[-1]*(1-fee); pnl = ev-e_usdc
        trades.append(Trade(et or t[-1], t[-1], ep, c[-1], (c[-1]-ep)/ep*100, pnl, "end"))
        cap = cap + ev

    win = [x for x in trades if x.pnl_usdc > 0]; lose = [x for x in trades if x.pnl_usdc <= 0]
    ret = cap-INIT_CAP; ret_p = (ret/INIT_CAP)*100
    wr = len(win)/len(trades)*100 if trades else 0
    avg_w = sum(x.pnl_pct for x in win)/len(win) if win else 0
    avg_l = sum(x.pnl_pct for x in lose)/len(lose) if lose else 0
    max_w = max((x.pnl_pct for x in trades), default=0)
    max_l = min((x.pnl_pct for x in trades), default=0)
    gw = sum(x.pnl_usdc for x in win); gl = abs(sum(x.pnl_usdc for x in lose))
    pf = gw/gl if gl > 0 else float('inf')

    dr = []
    for d in range(1, len(eq)):
        if eq[d-1] != 0: dr.append((eq[d]-eq[d-1])/eq[d-1])
    sh = 0
    if len(dr) > 1:
        ad = sum(dr)/len(dr)
        sd = math.sqrt(sum((r-ad)**2 for r in dr)/len(dr))
        sh = (ad/sd*math.sqrt(365)) if sd > 0 else 0

    hold = (sum((x.exit-x.entry).total_seconds()/60 for x in trades if x.exit and x.entry)/len(trades)
            if trades else 0)

    return Result(s.value, p, round(ret_p,2), round(ret,2), round(wr,1), len(trades),
                  len(win), len(lose), round(max_dd,2), round(sh,2), round(pf,2),
                  round(avg_w,2), round(avg_l,2), round(max_w,2), round(max_l,2),
                  round(hold,0), trades, eq)

def _empty(n, p):
    return Result(n,p,0,0,0,0,0,0,0,0,0,0,0,0,0,0,[],[])

def gen_params(s: Strategy):
    base = {"fee": 0.003}
    if s == Strategy.SMA_TREND:
        for sf in [5,10,15,20]:
            for ss in [20,30,40,50]:
                if sf >= ss: continue
                for sl in [0.02,0.03,0.04,0.05]:
                    for tp in [0.03,0.05,0.07,0.10]:
                        for pos in [0.25,0.50,0.75]:
                            yield {**base, "sf":sf, "ss":ss, "sl":sl, "tp":tp, "pos":pos}
    elif s == Strategy.RSI_MOM:
        for rp in [7,10,14]:
            for sl in [0.02,0.03,0.04,0.05]:
                for tp in [0.03,0.05,0.07,0.10]:
                    for pos in [0.25,0.50,0.75]:
                        for em in [">50",">30"]:
                            yield {**base, "rsi_p":rp, "sl":sl, "tp":tp, "pos":pos, "entry_mode":em}
    elif s == Strategy.BOLL:
        for bp in [15,20,25]:
            for bs in [1.5,2.0,2.5]:
                for sl in [0.02,0.03,0.04]:
                    for tp in [0.03,0.05,0.07]:
                        for pos in [0.25,0.50]:
                            yield {**base, "bb_p":bp, "bb_s":bs, "sl":sl, "tp":tp, "pos":pos}
    elif s == Strategy.MACD:
        for sl in [0.02,0.03,0.04,0.05]:
            for tp in [0.03,0.05,0.07,0.10]:
                for pos in [0.25,0.50,0.75]:
                    yield {**base, "sl":sl, "tp":tp, "pos":pos}

def print_r(r: Result, tag: str = ""):
    p = r.params
    desc = f"{r.name.upper()}"
    if "sf" in p: desc += f" SMA({p['sf']}/{p['ss']})"
    if "rsi_p" in p: desc += f" RSI({p['rsi_p']}) {p.get('entry_mode','')}"
    if "bb_p" in p: desc += f" BB({p['bb_p']}/{p['bb_s']})"
    desc += f" SL:{p.get('sl',0)*100:.0f}% TP:{p.get('tp',0)*100:.0f}% Pos:{p.get('pos',0)*100:.0f}%"
    print(f"  [{tag}] {desc}")
    print(f"    Ret: {r.ret_pct:>+8.2f}%  Win: {r.wr:>5.1f}%  N:{r.n:>3d}  "
          f"DD:{r.dd:>5.2f}%  Sharpe:{r.sharpe:>6.2f}  PF:{r.pf:>6.2f}")
    print(f"    W:{r.w} L:{r.l}  AvgW:{r.avg_w:+.2f}%  AvgL:{r.avg_l:+.2f}%  "
          f"Hold:{r.hold_m:.0f}m")
    if r.trades:
        last = []
        for t in r.trades[-5:]:
            s = f"{t.pnl_pct:+.1f}%"
            last.append(f"{t.reason} {s}")
        print(f"    Trades: {' | '.join(last)}")

def save(rs: list[Result], name: str):
    path = Path(f"data/backtests/bnb_hack_{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [{
        "strategy": r.name, "params": r.params,
        "return_pct": r.ret_pct, "win_rate": r.wr, "num_trades": r.n,
        "max_dd": r.dd, "sharpe": r.sharpe, "profit_factor": r.pf,
        "trades": [{"entry":t.entry.isoformat(),"exit":t.exit.isoformat(),
                    "entry_px":t.entry_px,"exit_px":t.exit_px,
                    "pnl_pct":round(t.pnl_pct,2),"pnl_usdc":round(t.pnl_usdc,2),
                    "reason":t.reason} for t in r.trades[-10:]],
    } for r in rs[:20]]
    with open(path,"w") as f: json.dump(data,f,indent=2)
    print(f"  → Saved: {path}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=[s.value for s in Strategy])
    parser.add_argument("--months", type=float, default=6)
    args = parser.parse_args()

    strats = [Strategy(args.strategy)] if args.strategy else list(Strategy)

    print(f"\n  ┌{'─'*50}┐")
    print(f"  │  BNB HACK — Multi-Strategy Backtest (${INIT_CAP})           │")
    print(f"  └{'─'*50}┘")

    for strat in strats:
        interval = "30m" if strat != Strategy.SMA_TREND else "1h"
        print(f"\n  {'═'*52}")
        print(f"  {strat.value.upper()} ({interval})")
        print(f"  {'═'*52}")
        k = await fetch(interval, args.months)
        print(f"  Data: {len(k)} candles ({args.months:.0f}mo)")

        params = list(gen_params(strat))
        print(f"  Params: {len(params)} combos")
        results = []
        for idx, p in enumerate(params):
            r = bt(k, strat, p)
            results.append(r)
            if (idx+1) % 25 == 0:
                print(f"    {idx+1}/{len(params)}", end="\r")
        print(f"    {len(params)}/{len(params)}")

        results.sort(key=lambda x: x.ret_pct, reverse=True)
        print(f"\n  TOP 5:")
        for i, r in enumerate(results[:5]): print_r(r, str(i+1))
        print(f"\n  WORST 5:")
        for i, r in enumerate(results[-5:]): print_r(r, str(len(results)-4+i))

        # Best Sharpe (min 3 trades)
        sh = sorted([r for r in results if r.n >= 3], key=lambda x: x.sharpe, reverse=True)
        if sh and sh[0].sharpe > 0:
            print(f"\n  ★ BEST SHARPE:")
            print_r(sh[0], f"★ S={sh[0].sharpe}")

        # Recent performance (last ~2 months)
        if len(k) > 500:
            recent = k[-len(k)//4:]
            print(f"\n  RECENT (last {len(recent)} candles):")
            recent_r = []
            for p in params[:20]:
                r = bt(recent, strat, p)
                if r.n >= 2: recent_r.append(r)
            recent_r.sort(key=lambda x: x.ret_pct, reverse=True)
            for i, r in enumerate(recent_r[:3]): print_r(r, f"R{i+1}")

        save(results[:20], strat.value)

if __name__ == "__main__":
    asyncio.run(main())
