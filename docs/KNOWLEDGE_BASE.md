# PolyEdge Knowledge Base & Visual Guide

Welcome to the complete visual knowledge base for PolyEdge. This guide explains every part of the dashboard and admin panel step-by-step, designed specifically for non-technical users and beginner traders.

---

## 1. The Main Dashboard Overview

When you first log in, you will see the **Overview** tab. This is your command center for monitoring the bot's health and performance.

![Dashboard Overview](assets/dashboard-overview.png)

*(If you don't see this image, make sure you are viewing the documentation with assets loaded)*

### 1.1 The Top Status Bar (The "Health Check")
At the very top of the screen, you will always see these critical metrics:
*   **Mode:** Shows either **SHADOW** (Paper Trading / Fake Money) or **LIVE** (Real Money). Always check this before expecting real profits or losses!
*   **Bank:** Your total available USDC balance in your Polymarket wallet.
*   **Equity:** Bank balance + the current value of all your active positions. This is your total net worth.
*   **P&L (Profit & Loss):** How much money the bot has made or lost overall. Green is good!
*   **Win Rate:** The percentage of trades that ended in profit. (e.g., 65% means out of 100 trades, 65 were winners).
*   **Exposure:** How much of your Bank balance is currently tied up in active trades.

### 1.2 The Navigation Menu
On the left side (or top menu), you will see tabs to navigate the bot:
*   **Overview:** High-level summary of performance and active trades.
*   **Trades:** A detailed history of every buy and sell the bot has executed.
*   **Signals:** Raw intelligence from the AI. Shows what the bot is "thinking" before it makes a trade.
*   **Markets:** Live view of all Polymarket events the bot is currently tracking (e.g., Politics, Crypto, Pop Culture).
*   **Leaderboard:** See which of the bot's internal strategies (like "News Search" or "Line Movement") are making the most money.
*   **Decisions:** Detailed logs of *why* the bot bought or sold a specific share.
*   **Performance:** Charts and graphs showing your equity growth over time.

---

## 2. Admin Settings & Configuration

The Admin panel is where you configure the bot's brain and give it the tools it needs to succeed.

*(Note: Admin panel layout may vary slightly depending on your exact version, but the sections remain the same.)*

### 2.1 API Keys (The Bot's Senses)
To make smart decisions, the bot needs to read the internet. You configure this in the Admin -> Settings tab.
*   **TAVILY_API_KEY / EXA_API_KEY / SERPER_API_KEY:** These are web search engines. They allow the bot to Google breaking news (like "Did the Fed raise rates?") before making a trade. 
*   **CRW_API_KEY:** Used for advanced data scraping.
*   **OPENAI / ANTHROPIC KEYS:** The "Brain" of the bot. These interpret the news and decide if a market share is cheap or expensive.

### 2.2 Web Search Configuration
You can control how the bot searches the internet:
*   **WEBSEARCH_ENABLED:** Turn this ON to allow the bot to read news. Highly recommended!
*   **WEBSEARCH_PROVIDER:** Choose your primary search engine (e.g., `tavily` or `exa`).
*   **WEBSEARCH_FALLBACK:** A backup engine in case the first one fails.
*   **MAX_RESULTS:** How many news articles the bot reads per market (Default: 5).

### 2.3 Telegram Alerts
Don't want to stare at the dashboard all day? 
*   **TELEGRAM_HIGH_CONFIDENCE_ALERTS:** Turn this ON. When the bot spots a massive opportunity (like a 5% sudden price drop), it will ping your phone via Telegram.

### 2.4 Strategies Panel
Under the **Admin -> Strategies** tab, you control the bot's "trading styles":
*   **Market Maker:** Provides liquidity by placing orders on both sides. Good for slow, steady pennies.
*   **News Catalyst:** Trades instantly when breaking news happens. High risk, high reward.
*   **Line Movement Detector:** Scans for sudden price crashes or spikes (e.g., a share drops from 50¢ to 45¢ in 5 minutes) and buys the dip.

---

## 3. How to Read a "Trade"

When looking at the **Trades** tab, you will see rows of data. Here is how to read them:

1.  **Market Name:** What the bet is about (e.g., "Will Bitcoin hit $100k in 2026?").
2.  **Side:** 
    *   `YES` - The bot believes the event *will* happen.
    *   `NO` - The bot believes the event *will not* happen.
3.  **Entry Price:** How much the bot paid per share (e.g., 40¢).
4.  **Current Price:** What the share is worth right now.
5.  **Status:** 
    *   `OPEN` - The trade is active.
    *   `CLOSED` - The bot sold the shares for a profit or loss.
    *   `RESOLVED` - The event finished (e.g., December 31st arrived), and Polymarket paid out $1.00 per winning share.

---

## 4. Quick Start: Your First 24 Hours

If you are just starting out, follow this checklist to ensure a safe launch:

1.  **Verify SHADOW Mode:** Look at the top left of the dashboard. Ensure it says `SHADOW`. Let the bot trade fake money for at least 24 hours.
2.  **Check API Keys:** Go to Admin -> Settings. Ensure your Web Search and AI keys are entered.
3.  **Enable Line Movement Detector:** Go to Admin -> Strategies. Make sure the `line_movement_detector` is toggled ON.
4.  **Watch the "Signals" Tab:** Check this tab after a few hours. If it is empty, your bot isn't finding any news. Check your API keys.
5.  **Review the Leaderboard:** After 24 hours, check which strategy made the most fake money. 
6.  **Go LIVE:** Only when you are comfortable, change the `.env` file `SHADOW_MODE=false`, restart the bot, and deposit a small amount of USDC (e.g., $50) to start compounding!

---

## Need Help?
*   If the bot stops making trades: Check the **Logs** or ensure your Polymarket wallet has USDC.
*   If P&L is negative: Remember that trading has ups and downs. However, if a specific strategy in the **Leaderboard** is constantly losing, go to Admin and turn that strategy OFF.


## Quick Reference (May 2026)

### Strategy Pipeline
```
PAPER (20 trades) → FRONTTEST (14d, WR≥55%) → SHADOW (7d) → LIVE
```

### Key Numbers
- DB PnL: $396 (reconciled with dashboard)
- Available: ~$1,600 USDC
- Strategies: 25 (all paper except disabled)
- Gate: Active — blocks unauthorized live orders
- Risk: $50/day per-strategy limit, 10% total drawdown limit

### Urgent Gaps
- WebSocket reconnection needed
- Strategy evolution loop (AGI auto-tune)
- Fronttest automation
