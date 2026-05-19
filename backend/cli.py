"""
CLI -- Polymarket Intelligence command-line tools.

Usage:
    python -m backend.cli analyze <wallet|username>
    python -m backend.cli analyze --rapid <wallet>
    python -m backend.cli compare <w1> <w2> [w3...]
    python -m backend.cli scan --min-volume 5000 --limit 20
    python -m backend.cli fingerprint <wallet>
    python -m backend.cli replicate <wallet>
    python -m backend.cli resolve <input>
    python -m backend.cli proxy <eoa>
    python -m backend.cli opportunities
    python -m backend.cli journal today
    python -m backend.cli journal --from 2026-01-01 --to 2026-05-19
"""

import argparse
import asyncio
import json
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy-loaded symbols (module-level so tests can patch them).
# Each is ``None`` until first use, then replaced with the real callable.
# ---------------------------------------------------------------------------

resolve_wallet = None
analyze_wallet = None
analyze_wallet_rapid = None
compare_wallets = None
find_profitable_traders = None
find_proxy_wallet = None
get_all_closed_positions = None
strategy_fingerprint = None
replicate_strategy = None
scan_for_opportunities = None
TradeJournal = None


def _load_globals():
    """Import heavy dependencies into module-level names (once)."""
    global resolve_wallet, analyze_wallet, analyze_wallet_rapid
    global compare_wallets, find_profitable_traders, find_proxy_wallet
    global get_all_closed_positions, strategy_fingerprint
    global replicate_strategy, scan_for_opportunities, TradeJournal

    if resolve_wallet is None:
        from backend.core.wallet_resolver import resolve_wallet as _rw
        resolve_wallet = _rw
    if analyze_wallet is None:
        from backend.core.wallet_analyzer import analyze_wallet as _aw
        analyze_wallet = _aw
    if analyze_wallet_rapid is None:
        from backend.core.wallet_analyzer import analyze_wallet_rapid as _awr
        analyze_wallet_rapid = _awr
    if compare_wallets is None:
        from backend.core.wallet_analyzer import compare_wallets as _cw
        compare_wallets = _cw
    if find_profitable_traders is None:
        from backend.core.wallet_scanner import find_profitable_traders as _fpt
        find_profitable_traders = _fpt
    if find_proxy_wallet is None:
        from backend.core.proxy_finder import find_proxy_wallet as _fpw
        find_proxy_wallet = _fpw
    if get_all_closed_positions is None:
        from backend.data.wallet_history import get_all_closed_positions as _gcp
        get_all_closed_positions = _gcp
    if strategy_fingerprint is None:
        from backend.strategies.fingerprint import strategy_fingerprint as _sf
        strategy_fingerprint = _sf
    if replicate_strategy is None:
        from backend.strategies.replication import replicate_strategy as _rs
        replicate_strategy = _rs
    if scan_for_opportunities is None:
        from backend.strategies.opportunity_detector import scan_for_opportunities as _so
        scan_for_opportunities = _so
    if TradeJournal is None:
        from backend.monitoring.trade_journal import TradeJournal as _TJ
        TradeJournal = _TJ


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------


async def cmd_analyze(args):
    """Full or rapid wallet analysis."""
    _load_globals()

    wallet_info = await resolve_wallet(args.wallet)
    proxy = wallet_info.proxy or args.wallet

    if args.rapid:
        result = await analyze_wallet_rapid(proxy)
    else:
        result = await analyze_wallet(proxy)

    if args.json:
        print(json.dumps(result.__dict__, default=str, indent=2))
    else:
        _print_analysis(result)


async def cmd_compare(args):
    """Compare multiple wallets."""
    _load_globals()

    results = await compare_wallets(args.wallets)

    if args.json:
        print(json.dumps([r.__dict__ for r in results], default=str, indent=2))
    else:
        _print_comparison(results)


async def cmd_scan(args):
    """Scan for profitable traders."""
    _load_globals()

    traders = await find_profitable_traders(
        min_volume=args.min_volume,
        min_trades=args.min_trades,
        max_results=args.limit,
        sort_by=args.sort_by,
    )

    if args.json:
        print(json.dumps([t.__dict__ for t in traders], indent=2))
    else:
        _print_scan_results(traders)


async def cmd_fingerprint(args):
    """Strategy fingerprint of a wallet."""
    _load_globals()

    wallet_info = await resolve_wallet(args.wallet)
    proxy = wallet_info.proxy or args.wallet
    positions = await get_all_closed_positions(proxy)

    if not positions:
        print(f"No positions found for {args.wallet}")
        return

    result = strategy_fingerprint(positions)

    if args.json:
        print(json.dumps(result.__dict__, default=str, indent=2))
    else:
        _print_fingerprint(result)


async def cmd_replicate(args):
    """Replicate strategy from a wallet."""
    _load_globals()

    result = await replicate_strategy(args.wallet, args.capital)

    if args.json:
        print(json.dumps(result.__dict__, default=str, indent=2))
    else:
        _print_replication(result)


async def cmd_resolve(args):
    """Resolve wallet from any input format."""
    _load_globals()

    result = await resolve_wallet(args.input)

    if args.json:
        print(json.dumps(result.__dict__, indent=2))
    else:
        print(f"EOA:    {result.eoa or 'N/A'}")
        print(f"Proxy:  {result.proxy or 'N/A'}")
        print(f"User:   {result.username or 'N/A'}")
        print(f"Method: {result.method}")
        print(f"Traded: {result.has_traded}")


async def cmd_proxy(args):
    """Find proxy wallet from EOA."""
    _load_globals()

    result = await find_proxy_wallet(args.eoa)

    if args.json:
        print(json.dumps({"eoa": args.eoa, "proxy": result}, indent=2))
    else:
        if result:
            print(f"Proxy: {result}")
        else:
            print("No proxy wallet found")


async def cmd_opportunities(args):
    """Scan for trading opportunities."""
    _load_globals()

    opps = await scan_for_opportunities()

    if args.json:
        print(json.dumps([o.__dict__ for o in opps], default=str, indent=2))
    else:
        _print_opportunities(opps)


async def cmd_journal(args):
    """Trade journal query."""
    _load_globals()

    journal = TradeJournal()

    if args.export:
        path = journal.export_csv(
            start_date=args.from_date, end_date=args.to_date
        )
        print(f"Exported to: {path}")
    elif args.summary:
        summary = journal.get_daily_summary(args.date)
        if args.json:
            print(json.dumps(summary.__dict__, default=str, indent=2))
        else:
            _print_daily_summary(summary)
    else:
        trades = journal.get_trades(
            start_date=args.from_date,
            end_date=args.to_date,
            limit=args.limit,
        )
        if args.json:
            print(
                json.dumps(
                    [t.__dict__ if hasattr(t, "__dict__") else t for t in trades],
                    default=str,
                    indent=2,
                )
            )
        else:
            _print_trades(trades)


# ---------------------------------------------------------------------------
# Pretty printers
# ---------------------------------------------------------------------------


def _print_analysis(result):
    print("=== Wallet Analysis ===")
    print(f"Wallet:       {result.wallet}")
    print(f"Positions:    {result.total_positions}")
    print(f"Total PnL:    ${result.total_pnl:.2f}")
    print(f"Win Rate:     {result.win_rate:.1%}")
    print(f"Profit Factor:{result.profit_factor:.2f}")
    print(f"Sharpe:       {result.sharpe_ratio:.2f}")
    print(f"Max Drawdown: ${result.max_drawdown:.2f}")
    print(f"Verdict:      {result.verdict}")
    print(f"Copy Rating:  {result.copy_trade_rating}/10")
    if result.red_flags:
        print(f"Red Flags:    {', '.join(result.red_flags)}")


def _print_comparison(results):
    print(f"{'Wallet':<15} {'PnL':>10} {'WR':>8} {'Trades':>8} {'PF':>6} {'Sharpe':>8}")
    print("-" * 60)
    for r in results:
        print(
            f"{r.wallet[:13]:<15} ${r.total_pnl:>8.2f} {r.win_rate * 100:>6.1f}% "
            f"{r.total_positions:>7} {r.profit_factor:>5.2f} {r.sharpe_ratio:>7.2f}"
        )


def _print_scan_results(traders):
    print(f"{'Wallet':<15} {'PnL':>10} {'WR':>8} {'Trades':>8} {'Volume':>10}")
    print("-" * 55)
    for t in traders:
        print(
            f"{t.wallet[:13]:<15} ${t.pnl:>8.2f} {t.win_rate * 100:>6.1f}% "
            f"{t.total_trades:>7} ${t.volume:>8.0f}"
        )


def _print_fingerprint(result):
    print("=== Strategy Fingerprint ===")
    print(f"Type:        {result.strategy_type}")
    print(f"Category:    {result.primary_category} ({result.primary_category_share:.0%})")
    print(f"Confidence:  {result.confidence:.2f}")
    print(f"Copy Rating: {result.copy_trade_suitability}/10")
    print(f"Replicable:  {result.is_replicable} ({result.replication_difficulty})")
    if result.red_flags:
        print(f"Red Flags:   {', '.join(result.red_flags)}")
    if result.green_flags:
        print(f"Green Flags: {', '.join(result.green_flags)}")


def _print_replication(result):
    print("=== Strategy Replication ===")
    print(f"Source:      {result.source_wallet}")
    print(f"Confidence:  {result.confidence_score:.2f}")
    print(f"Ready:       {result.is_ready_for_live}")
    print(f"Rules:       {len(result.rules)}")
    if result.paper_results:
        pr = result.paper_results
        print(f"Paper PnL:   ${pr.get('pnl', 0):.2f}")
        print(f"Paper WR:    {pr.get('win_rate', 0) * 100:.1f}%")


def _print_opportunities(opps):
    if not opps:
        print("No opportunities found")
        return
    print(f"{'Type':<20} {'Market':<30} {'EV':>8} {'Conf':>6}")
    print("-" * 70)
    for o in opps:
        print(
            f"{o.type:<20} {o.market_title[:28]:<30} "
            f"${o.expected_value:>6.2f} {o.confidence:>5.0%}"
        )


def _print_daily_summary(s):
    print(f"=== Daily Summary: {s.date} ===")
    print(f"Trades:    {s.total_trades}")
    print(f"PnL:       ${s.total_pnl:.2f}")
    print(f"Win Rate:  {s.win_rate * 100:.1f}%")
    print(f"Volume:    ${s.volume:.2f}")


def _print_trades(trades):
    if not trades:
        print("No trades found")
        return
    print(f"{'Time':<20} {'Market':<25} {'Side':<5} {'Size':>8} {'PnL':>10}")
    print("-" * 75)
    for t in trades[:20]:
        d = t.__dict__ if hasattr(t, "__dict__") else t
        print(
            f"{str(d.get('timestamp', d.get('created_at', ''))):<20} "
            f"{str(d.get('market_ticker', ''))[:23]:<25} "
            f"{str(d.get('direction', d.get('side', ''))):<5} "
            f"${d.get('size', 0):>6.2f} ${d.get('pnl', 0):>8.2f}"
        )


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Polymarket Intelligence CLI")
    parser.add_argument("--json", action="store_true", help="JSON output")

    sub = parser.add_subparsers(dest="command")

    # analyze
    p_analyze = sub.add_parser("analyze", help="Analyze a wallet")
    p_analyze.add_argument("wallet", help="Wallet address or username")
    p_analyze.add_argument("--rapid", action="store_true", help="Rapid analysis mode")

    # compare
    p_compare = sub.add_parser("compare", help="Compare wallets")
    p_compare.add_argument("wallets", nargs="+", help="Wallet addresses")

    # scan
    p_scan = sub.add_parser("scan", help="Scan for profitable traders")
    p_scan.add_argument("--min-volume", type=float, default=1000)
    p_scan.add_argument("--min-trades", type=int, default=50)
    p_scan.add_argument("--limit", type=int, default=20)
    p_scan.add_argument(
        "--sort-by",
        default="pnl",
        choices=["pnl", "win_rate", "volume", "sharpe"],
    )

    # fingerprint
    p_fp = sub.add_parser("fingerprint", help="Strategy fingerprint")
    p_fp.add_argument("wallet", help="Wallet address or username")

    # replicate
    p_rep = sub.add_parser("replicate", help="Replicate strategy")
    p_rep.add_argument("wallet", help="Source wallet")
    p_rep.add_argument(
        "--capital", type=float, default=1000, help="Available capital"
    )

    # resolve
    p_res = sub.add_parser("resolve", help="Resolve wallet input")
    p_res.add_argument("input", help="Address or username")

    # proxy
    p_proxy = sub.add_parser("proxy", help="Find proxy wallet")
    p_proxy.add_argument("eoa", help="EOA address")

    # opportunities
    sub.add_parser("opportunities", help="Scan for opportunities")

    # journal
    p_journal = sub.add_parser("journal", help="Trade journal")
    p_journal.add_argument("date", nargs="?", help="Date (YYYY-MM-DD)")
    p_journal.add_argument("--from", dest="from_date", help="Start date")
    p_journal.add_argument("--to", dest="to_date", help="End date")
    p_journal.add_argument("--summary", action="store_true", help="Daily summary")
    p_journal.add_argument("--export", action="store_true", help="Export to CSV")
    p_journal.add_argument("--limit", type=int, default=50)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    # Inject --json default when not set (subcommands don't inherit it)
    if not hasattr(args, "json"):
        args.json = False

    handlers = {
        "analyze": cmd_analyze,
        "compare": cmd_compare,
        "scan": cmd_scan,
        "fingerprint": cmd_fingerprint,
        "replicate": cmd_replicate,
        "resolve": cmd_resolve,
        "proxy": cmd_proxy,
        "opportunities": cmd_opportunities,
        "journal": cmd_journal,
    }

    handler = handlers.get(args.command)
    if handler:
        asyncio.run(handler(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
