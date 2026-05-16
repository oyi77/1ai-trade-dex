"""Trade Pattern Analysis — categorize and analyze poly-history.csv trades."""

import csv
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from statistics import median, mean

# ── Category patterns ──────────────────────────────────────────────
CATEGORY_PATTERNS = {
    "Crypto/Bitcoin": [
        r"Bitcoin Up or Down",
        r"price of Bitcoin",
        r"Bitcoin.*above",
        r"Bitcoin.*below",
    ],
    "Politics/Trump": [
        r"Trump",
        r"Xi Jinping",
        r"presidential",
        r"president",
    ],
    "Sports": [
        r"Cubs", r"Braves", r"Phillies", r"Red Sox", r"Orioles", r"Nationals",
        r"O\.?U\.", r"Over/Under",
        r"Rinderknech", r"Sinner", r"Swiatek", r"Svitolina",
        r"Internazionali", r"Roland Garros", r"ATP", r"WTA",
        r"Padres", r"Giants", r"Cardinals", r"Mets", r"Yankees",
        r"Twins", r"Guardians", r"Royals", r"Rangers", r"Astros",
        r"Angels", r"Mariners", r"Reds", r"Pirates", r"Brewers",
        r"Dodgers", r"Rockies", r"Tigers", r"White Sox",
        r"Blue Jays", r"Rays", r"Marlins", r"Braves",
        r"Rangers vs", r"Angels vs", r"Padres vs", r"Giants vs",
        r"Mariners vs", r"Twins vs", r"Tigers vs",
    ],
    "Esports": [
        r"LoL:", r"Dota", r"CS2", r"Valorant",
        r"Ozarox", r"Team Phoenix", r"Esports",
        r"9z", r"FURIA", r"BO3", r"BO5",
        r"TCL", r"LEC", r"LCS", r"LCK", r"LPL",
    ],
    "Weather": [
        r"temperature", r"weather", r"forecast",
        r"rain", r"snow", r"hurricane",
    ],
}


def classify_market(name: str) -> str:
    """Classify a market name into a category."""
    for category, patterns in CATEGORY_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, name, re.IGNORECASE):
                return category
    return "Other"


def parse_timestamp(ts_str: int) -> datetime:
    """Parse unix timestamp to datetime."""
    return datetime.fromtimestamp(int(ts_str), tz=timezone.utc)


def main():
    # Read CSV with utf-8-sig to handle BOM
    with open("poly-history.csv", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"=== TRADE PATTERN ANALYSIS ===")
    print(f"Total trades: {len(rows)}")
    print()

    # ── 1. Categorize trades ────────────────────────────────────────
    for row in rows:
        row["_category"] = classify_market(row["marketName"])
        row["_usdc"] = float(row["usdcAmount"])
        row["_ts"] = parse_timestamp(row["timestamp"])

    categories = defaultdict(list)
    for row in rows:
        categories[row["_category"]].append(row)

    # ── 2. Per-category metrics ────────────────────────────────────
    print("=== PER-CATEGORY METRICS ===")
    print(f"{'Category':<20} {'Trades':>7} {'Total USDC':>12} {'Avg Size':>10} {'Median':>10} {'Win Rate':>10}")
    print("-" * 75)

    for cat in sorted(categories, key=lambda c: len(categories[c]), reverse=True):
        trades = categories[cat]
        count = len(trades)
        total = sum(t["_usdc"] for t in trades)
        avg = total / count if count else 0
        med = median([t["_usdc"] for t in trades]) if trades else 0
        buys = sum(1 for t in trades if t["action"] == "Buy")
        sells = sum(1 for t in trades if t["action"] == "Sell")
        redeems = sum(1 for t in trades if t["action"] == "Redeem")
        win_rate = (sells + redeems) / buys * 100 if buys else 0
        print(f"{cat:<20} {count:>7} {total:>12.2f} {avg:>10.2f} {med:>10.2f} {win_rate:>9.1f}%")

    print()

    # ── 3. Action distribution ─────────────────────────────────────
    print("=== ACTION DISTRIBUTION ===")
    actions = Counter(r["action"] for r in rows)
    for action, count in actions.most_common():
        print(f"  {action:<15} {count:>5} ({count/len(rows)*100:.1f}%)")
    print()

    # ── 4. Time-of-day patterns (Bitcoin windows) ──────────────────
    print("=== BITCOIN TIME-OF-DAY PATTERNS ===")
    btc_trades = [r for r in rows if r["_category"] == "Crypto/Bitcoin"]
    if btc_trades:
        # Group by hour
        by_hour = defaultdict(list)
        for t in btc_trades:
            by_hour[t["_ts"].hour].append(t)
        for hour in sorted(by_hour):
            trades = by_hour[hour]
            total = sum(t["_usdc"] for t in trades)
            print(f"  {hour:02d}:00 UTC  {len(trades):>4} trades  ${total:>10.2f}")

        # 5-minute window analysis
        print("\n  Top 5-min Bitcoin windows:")
        by_window = defaultdict(list)
        for t in btc_trades:
            ts = t["_ts"]
            window = f"{ts.strftime('%H')}:({ts.minute // 5 * 5:02d}-{ts.minute // 5 * 5 + 5:02d})"
            key = f"{ts.strftime('%Y-%m-%d %H')}:{ts.minute // 5 * 5:02d}"
            by_window[key].append(t)
        for key, trades in sorted(by_window.items(), key=lambda x: sum(t["_usdc"] for t in x[1]), reverse=True)[:10]:
            total = sum(t["_usdc"] for t in trades)
            print(f"  {key}  {len(trades):>3} trades  ${total:>10.2f}")
    print()

    # ── 5. Market clustering (Trump/Xi correlated exposure) ────────
    print("=== MARKET CLUSTERING ANALYSIS ===")
    trump_trades = [r for r in rows if "Trump" in r["marketName"] or "Xi Jinping" in r["marketName"]]
    if trump_trades:
        by_market = defaultdict(list)
        for t in trump_trades:
            by_market[t["marketName"]].append(t)
        total_trump = sum(t["_usdc"] for t in trump_trades)
        print(f"  Trump/Xi cluster: {len(trump_trades)} trades, ${total_trump:.2f} total")
        for m, trades in sorted(by_market.items(), key=lambda x: sum(t["_usdc"] for t in x[1]), reverse=True):
            total = sum(t["_usdc"] for t in trades)
            print(f"    {m[:70]:<70} {len(trades):>4} trades  ${total:>8.2f}")
    print()

    # ── 6. Overall stats ───────────────────────────────────────────
    all_usdc = [r["_usdc"] for r in rows]
    print("=== OVERALL STATISTICS ===")
    print(f"  Total trades: {len(rows)}")
    print(f"  Total USDC: ${sum(all_usdc):.2f}")
    print(f"  Mean trade: ${mean(all_usdc):.2f}")
    print(f"  Median trade: ${median(all_usdc):.2f}")
    print(f"  Min trade: ${min(all_usdc):.5f}")
    print(f"  Max trade: ${max(all_usdc):.2f}")

    ts_all = [r["_ts"] for r in rows]
    print(f"  Date range: {min(ts_all).strftime('%Y-%m-%d %H:%M')} to {max(ts_all).strftime('%Y-%m-%d %H:%M')} UTC")
    print(f"  Unique markets: {len(set(r['marketName'] for r in rows))}")

    buys = sum(1 for r in rows if r["action"] == "Buy")
    sells = sum(1 for r in rows if r["action"] == "Sell")
    print(f"  Buys: {buys}, Sells: {sells} (ratio: {buys}:{sells})")
    print()

    # ── 7. Top markets ─────────────────────────────────────────────
    print("=== TOP 15 MARKETS BY VOLUME ===")
    by_market = defaultdict(list)
    for r in rows:
        by_market[r["marketName"]].append(r)
    for m, trades in sorted(by_market.items(), key=lambda x: sum(t["_usdc"] for t in x[1]), reverse=True)[:15]:
        total = sum(t["_usdc"] for t in trades)
        cat = trades[0]["_category"]
        print(f"  {cat:<18} {len(trades):>4} trades  ${total:>10.2f}  {m[:60]}")


if __name__ == "__main__":
    main()
