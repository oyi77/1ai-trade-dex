import csv
from collections import Counter
from datetime import datetime

with open('poly-history.csv', 'r') as f:
    reader = csv.DictReader(f)
    rows = list(reader)

print(f'Total trades: {len(rows)}')
actions = Counter(r['action'] for r in rows)
print(f'Actions: {dict(actions)}')

total_usdc = sum(float(r['usdcAmount']) for r in rows)
print(f'Total USDC: ${total_usdc:,.2f}')

timestamps = [int(r['timestamp']) for r in rows if r['timestamp'].isdigit()]
if timestamps:
    earliest = datetime.fromtimestamp(min(timestamps))
    latest = datetime.fromtimestamp(max(timestamps))
    print(f'Date range: {earliest} to {latest}')
    print(f'Days: {(latest - earliest).days}')

markets = Counter(r['marketName'] for r in rows)
print(f'Unique markets: {len(markets)}')
print('Top 10 markets:')
for m, c in markets.most_common(10):
    usdc = sum(float(r['usdcAmount']) for r in rows if r['marketName'] == m)
    print(f'  {c} trades, ${usdc:.2f}: {m[:70]}')

tokens = Counter(r['tokenName'] for r in rows)
print(f'Token distribution: {dict(tokens.most_common(5))}')

sizes = [float(r['usdcAmount']) for r in rows]
print(f'Avg trade: ${sum(sizes)/len(sizes):.4f}')
print(f'Min: ${min(sizes):.4f}, Max: ${max(sizes):.4f}')
print(f'Median: ${sorted(sizes)[len(sizes)//2]:.4f}')

# Category analysis
categories = {
    'Bitcoin/BTC': 0, 'Trump/Politics': 0, 'Sports': 0,
    'Esports': 0, 'Weather': 0, 'Other': 0
}
cat_usdc = {k: 0.0 for k in categories}
for r in rows:
    name = r['marketName'].lower()
    usdc = float(r['usdcAmount'])
    if 'bitcoin' in name or 'btc' in name or 'price of bitcoin' in name:
        categories['Bitcoin/BTC'] += 1; cat_usdc['Bitcoin/BTC'] += usdc
    elif 'trump' in name or 'xi jinping' in name or 'eurovision' in name or 'hantavirus' in name or 'gemini' in name or 's&p' in name or 'elon' in name:
        categories['Trump/Politics'] += 1; cat_usdc['Trump/Politics'] += usdc
    elif 'cubs' in name or 'phillies' in name or 'orioles' in name or 'braves' in name or 'red sox' in name or 'nationals' in name or 'o/u' in name:
        categories['Sports'] += 1; cat_usdc['Sports'] += usdc
    elif 'lol' in name or 'ozarox' in name or 'phoenix' in name or 'tcl' in name:
        categories['Esports'] += 1; cat_usdc['Esports'] += usdc
    elif 'temperature' in name or 'weather' in name or 'seoul' in name:
        categories['Weather'] += 1; cat_usdc['Weather'] += usdc
    elif 'swiatek' in name or 'svitolina' in name or 'tennis' in name or 'internazionali' in name:
        categories['Sports'] += 1; cat_usdc['Sports'] += usdc
    else:
        categories['Other'] += 1; cat_usdc['Other'] += usdc

print('\nCategory breakdown:')
for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
    if count > 0:
        print(f'  {cat}: {count} trades, ${cat_usdc[cat]:.2f}')
