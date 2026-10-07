# US Broker/Platform APIs for Algorithmic Options Trading (Paper + Live), as of 2026-10-07

Scope: Alpaca, Interactive Brokers (TWS API / Client Portal / Web API), Tradier, Charles Schwab Trader API, tastytrade, TradeStation, Webull OpenAPI, E*TRADE (Morgan Stanley), plus Public.com as a newer entrant. US retail accounts.

Method notes, so the writer can judge confidence:
- Direct page fetches to docs.alpaca.markets and quantconnect.com were blocked by the research environment's egress proxy, and so was GitHub API access (no star or issue counts). Most findings come from web-search extracts of official docs and pricing pages, plus third-party reviews where flagged. Package release dates were checked directly against the PyPI JSON API on 2026-10-07.
- Third-party "best broker" reviews (brokerchooser, tradealgo, pickmytrade, investormint) may earn affiliate revenue. Facts that come only from them are flagged.

---

## 1. Options order support via API (single vs multi-leg, order types, SPX/XSP, exercise/assignment)

### Takeaway
Every major broker here accepts multi-leg options orders via API. The differences are in index-option coverage and in documentation quality. Alpaca now supports multi-leg (L3, since Feb 2025) and live index options (SPX/SPXW/XSP/VIX). IBKR, Tradier, tastytrade, Schwab and TradeStation support multi-leg plus index options. Webull's API excludes index options in at least the HK region. Schwab's multi-leg order structure is poorly documented.

### Cited Findings
**Alpaca**
- Multi-leg (Level 3) options reached paper accounts in January 2025 and the live Trading API in February 2025. They're submitted through the standard POST /orders endpoint. Supported strategies: straddles, strangles, iron butterflies, iron condors, and credit/debit/calendar spreads. — [Alpaca changelog](https://docs.alpaca.markets/us/changelog/multi-leg-level-3-options-trading-in-paper); [Alpaca blog](https://alpaca.markets/blog/level-3-options-trading-now-available-with-alpacas-trading-api/)
- Index options moved from paper to live API trading. Covered contracts: SPX, SPXW, VIX, VIXW, DJX and XSP ("more coming soon"). They're cash-settled and European-style, so no early exercise or assignment. AM-settled contracts may have a morning order cutoff on expiration day. — [Alpaca blog: index options launch](https://alpaca.markets/blog/alpaca-launches-index-options-via-trading-api); [Finance Magnates](https://www.financemagnates.com/institutional-forex/alpaca-moves-index-options-from-paper-trading-to-live-api-access/) (exact launch date not captured; see Gaps)
- Alpaca doesn't provide index (underlying) market data yet. "Support for index market data is planned for a future release." — [Alpaca blog: index options launch](https://alpaca.markets/blog/alpaca-launches-index-options-via-trading-api)
- Options levels: paper accounts get Level 3 automatically. Live accounts must apply for an options level. — [Alpaca changelog](https://docs.alpaca.markets/us/changelog/multi-leg-level-3-options-trading-in-paper); [QuantConnect Alpaca docs via search](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/alpaca)

**Charles Schwab Trader API**
- schwab-py supports multi-leg orders via `add_option_leg()`. Its docs warn: "due to the complexity of these orders and the lack of any real documentation, we cannot definitively say how to structure these orders." Spread price is the net debit or credit. — [schwab-py OrderBuilder docs](https://schwab-py.readthedocs.io/en/latest/order-builder.html)
- A trader on Elite Trader reports sending 4-leg butterfly and condor orders daily via the Schwab API. The thread is about 14 months old and anecdotal. — [Elite Trader thread](https://www.elitetrader.com/et/threads/schwab-api-anyone-doing-4-leg-option-orders.385924/)
- Through QuantConnect, Schwab supports equities, options and index options, with market, limit, stop-market and combo orders. — [QuantConnect Schwab brokerage docs](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/charles-schwab)
- Multi-leg orders combined with OCO/OTO are described as "experimental" in the developer community. Secondary source. — [MyLinedChart](https://mylinedchart.com/resources/articles/schwab-api-for-technical-traders-workflow-fit-checklist)

**tastytrade**
- The QuantConnect brokerage listing shows equity, equity options, futures, futures options and index options. A QC forum reply confirms index options are supported, though one user had earlier trouble with SPX options. — [QuantConnect tastytrade brokerage page](https://www.quantconnect.com/brokerages/tastytrade); [QuantConnect tastytrade LEAN CLI docs](https://www.quantconnect.com/docs/v2/lean-cli/live-trading/brokerages/tastytrade)
- The official API has an orders spec (multi-leg is native to tastytrade's order model). — [tastytrade Open API spec: orders](https://developer.tastytrade.com/open-api-spec/orders/)

**Tradier**
- Tradier markets itself to SPX/0DTE traders and charges explicit index-option fees, which implies index options are tradable. — [Tradier pricing](https://tradier.com/individuals/pricing); [Tradier "Trade SPX & 0DTE"](https://trade.tradier.com/tradepro/)
- Through QuantConnect, Tradier covers US equities and equity options. — [QuantConnect Tradier docs](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/tradier)

**TradeStation**
- One 2026 review says the API exposes multi-leg options orders plus bracket, OCO and OSO order types. This is third-party, not official docs. — [PickMyTrade review 2026](https://blog.pickmytrade.io/tradestation-review-2026-best-broker-for-automated-traders/)
- TradeStation's options page advertises index options, single-leg and multi-leg pricing. — [TradeStation options](https://www.tradestation.com/trading-products/options/)

**Webull OpenAPI**
- The official Webull CLI docs list `order option strategy` (multi-leg) alongside `order option submit` (single-leg). — [Webull developer CLI docs](https://developer.webull.com/apis/docs/AI-friendly-Resources/cli/)
- Webull HK Trading API docs say the API supports US options "excluding index options." US-portal confirmation wasn't found. — [Webull HK trade API](https://developer.webull.hk/apis/docs/trade-api/trade)
- The Webull EU API feature matrix lists market, limit and stop orders for US options. — [Webull EU Trading API overview](https://developer.webull.eu/apis/docs/trade-api/overview)
- QuantConnect announced a Webull integration covering equities, options and index options. This conflicts with the HK doc's index-option exclusion; the US region may differ. — [QuantConnect announcement](https://www.quantconnect.com/announcements/20912/integration-with-webull-for-equities-options-and-index-option-trading/p0)

**Interactive Brokers**
- IBKR offers the broadest product coverage, with combo (BAG) orders, index options and greeks via TWS API (see section 3). IBKR's own option-greeks API docs exist. — [IBKR TWS API option greeks](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-live/option-greeks/introduction)

**E*TRADE**
- The REST API covers accounts, portfolios, quotes, option chains and order placement. — [API Evangelist E*TRADE listing](https://apis.apievangelist.com/store/etrade); [E*TRADE developer portal](https://developer.etrade.com/)

**Public.com (newer entrant)**
- The API supports single-leg market, limit, stop and stop-limit options orders and multi-leg options strategies. Option chains are queryable by symbol, expiration and type. — [Public API page](https://public.com/get/api)

### Inferences
- For SPX/XSP swing trading, IBKR, tastytrade, Tradier, Schwab and (since its index launch) Alpaca are all viable on paper. Webull's index-option support via API is unclear or region-dependent.
- Alpaca's lack of index market data means an SPX strategy on Alpaca would need a separate data source for the underlying index level.
- Schwab works for multi-leg in practice, but expect trial-and-error on order JSON.

### Gaps
- Exact launch date of Alpaca live index options wasn't captured (the blog post was found but not fetched due to egress blocking).
- No official TradeStation or E*TRADE docs were verified on multi-leg order schemas, order types or index options.
- Per-broker API exercise/assignment handling (e.g., do-not-exercise instructions, early-assignment notifications via API) wasn't found for any broker except Alpaca's European-style note.

---

## 2. Paper trading / sandbox for options

### Takeaway
IBKR (full paper account, real market prices, $1M) and Alpaca (free paper with automatic L3 multi-leg) have the most usable paper environments for options. Tradier's sandbox uses delayed data. tastytrade's sandbox is limited (resets every 24h, limited symbols, no fill control). Schwab has no paper trading API. Webull added OpenAPI paper trading in July 2026. E*TRADE's sandbox returns canned responses, not real simulation.

### Cited Findings
- **IBKR:** All new clients get a paper account with $1,000,000 of paper equity. Paper trades aren't sent to exchanges, but execution prices "will be determined by real market prices and sizes." Paper accounts can be used via TWS/API. The paper user has no data subscriptions of its own and gets delayed data unless live data sharing is enabled. If live and paper sessions run at once, they must be on the same device to get live data. — [IBKR KB: Market Data Considerations for the Paper Trading Account](https://ibkb.interactivebrokers.com/article/1719); [IBKR paper trader KB](https://ibkb.interactivebrokers.com/tag/paper-trader)
- **Alpaca:** All paper accounts automatically get Level 3 (multi-leg). Multiple paper accounts are supported for testing strategies in parallel. — [Alpaca changelog](https://docs.alpaca.markets/us/changelog/multi-leg-level-3-options-trading-in-paper)
- **Alpaca:** Index options were available in paper before moving to live. — [Finance Magnates](https://www.financemagnates.com/institutional-forex/alpaca-moves-index-options-from-paper-trading-to-live-api-access/)
- **Tradier:** The sandbox is "a paper trading account to test your integration with our API," with delayed market data. All users get API tokens for both live and sandbox. — [Tradier docs endpoints](https://docs.tradier.com/docs/endpoints)
- **Tradier via QuantConnect:** In paper mode, account activity and streaming market data aren't available. — [QuantConnect Tradier docs](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/tradier)
- **tastytrade:** The official sandbox exists (cert environment, separate credentials and base URLs). — [tastytrade OAuth2 docs](https://developer.tastytrade.com/docs/authentication/oauth2/)
- **tastytrade:** Per the unofficial SDK docs (v12.4.0, possibly stale), the sandbox has limited symbol support, no ability to control fills, and resets every 24 hours. The SDK maintainers offer a proprietary paper trading API emulating the real API, for sponsors at $30/month or more. — [tastytrade SDK paper docs](https://tastyworks-api.readthedocs.io/en/v12.4.0/paper.html)
- **Schwab:** QuantConnect says Schwab has no paper trading, so QC's internal paper modeling is the testing route. — [QuantConnect Schwab docs](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/charles-schwab). One third-party table claims "Yes" for paper; that conflicts and is less specific. — [TradeAlgo options APIs 2026](https://www.tradealgo.com/trading-guides/options/options-trading-apis-how-to-build-automated-options-strategies-in-2026)
- **Webull:** On July 21, 2026, Webull announced a paperTrade refresh. It added OpenAPI access for paper trading across six asset classes including options, "advanced options order functionality" and multi-leg strategies, and a rebuilt pricing engine designed to model real-time execution and slippage. — [Barchart/press release](https://www.barchart.com/story/news/3382513/webull-unveils-enhanced-paper-trading-experience-with-professional-grade-and-openapi-multi-asset-simulation); [Finviz](https://finviz.com/news/370497/webull-unveils-enhanced-paper-trading-experience-with-professional-grade-and-openapi-multi-asset-simulation)
- **E*TRADE:** The sandbox key comes from an automated generator. Per a CRAN package README citing E*TRADE docs, the sandbox "will return trades different from what was entered" and exists only to verify that the entry is valid. — [E*TRADE developer](https://developer.etrade.com/); [etrader R package README](https://search.r-project.org/CRAN/packages/etrader/readme/README.html)
- **TradeStation:** A simulated trading environment is reachable via the API. Whether it covers multi-leg options wasn't confirmed. — [PickMyTrade review 2026](https://blog.pickmytrade.io/tradestation-review-2026-best-broker-for-automated-traders/)
- **Public.com:** TradersPost's Public integration has no paper environment (live only, single-leg only). No Public-native paper API was found. — [TradersPost blog](https://blog.traderspost.io/article/publiccom-traderspost-integration)

### Inferences
- A "same code, flip a URL/port" paper-to-live path works cleanly on Alpaca (paper vs live base URL), IBKR (paper vs live login on Gateway) and Tradier (sandbox token). On Schwab you'd have to build your own simulator or use QuantConnect's.
- Paper fill realism: IBKR's is reportedly closest, since it uses real prices and sizes. Alpaca's paper fill logic for options wasn't verified (see Gaps). Webull's new engine claims slippage modeling but is unproven.

### Gaps
- Alpaca's paper options fill model (mid vs NBBO, partial fills, assignment simulation) couldn't be verified because the docs fetch was blocked.
- Whether TradeStation SIM supports multi-leg options via API wasn't confirmed.
- No independent user reports on Webull's new OpenAPI paper engine (it's only about 2.5 months old).

---

## 3. Market data: real-time options quotes, greeks, streaming, cost, historical

### Takeaway
IBKR provides streaming options quotes with greeks, but you need paid OPRA subscriptions and a funded Pro account. Alpaca's real-time OPRA costs $99/mo (Algo Trader Plus); the free tier is "indicative" only, and historical options data only goes back to Feb 2024. Schwab data is free for account holders. Tradier includes real-time data with API plans. No broker API is a good source of deep historical options data for backtesting; plan on a third-party vendor.

### Cited Findings
- **Alpaca:** The free Basic plan has "indicative" options data, a randomized derivative of OPRA with trades delayed 15 min. Alpaca staff say it shouldn't be used for live trading. Algo Trader Plus at $99/month gives real-time OPRA, unlimited WebSocket symbols and up to 10,000 requests/min. — [Alpaca market data docs](https://docs.alpaca.markets/us/v1.4.2/docs/about-market-data-api); [Alpaca forum](https://forum.alpaca.markets/t/how-to-get-the-current-market-price-of-an-option-shown-in-alpaca-ui/14769); [apis.io Alpaca plans](https://apis.io/plans/alpaca-markets/alpaca-markets-plans-pricing/)
- **Alpaca:** Historical options data is available only since February 2024. Bars come from OPRA data. The free plan can access OPRA data older than 15 minutes. — [Alpaca historical option data docs](https://docs.alpaca.markets/docs/historical-option-data); [Alpaca forum](https://forum.alpaca.markets/t/does-historical-options-data-starts-from-2024-or-my-script-is-wrong/13976)
- **Alpaca:** A user with Algo Trader Plus reported historical option quotes returning HTTP 404 while trades and bars worked. No resolution was found. — [Alpaca forum: historical options request](https://forum.alpaca.markets/t/historical-options-request/19218)
- **Alpaca:** No index market data (SPX level) is available yet. — [Alpaca blog](https://alpaca.markets/blog/alpaca-launches-index-options-via-trading-api)
- **IBKR:** Most securities require a Level 1 subscription for API data. API data needs a funded IBKR Pro account with roughly $500 in the account on top of subscription costs. The "US Securities Snapshot and Futures Value Bundle" costs $10/mo, waived at $30+/mo in commissions. An OPRA Top of Book subscription exists (price not captured). Trading SPX reportedly needs OPRA (NP, L1) plus a Cboe One add-on (third-party guide). — [IBKR API market data subscriptions](https://www.interactivebrokers.com/campus/ibkr-api-page/market-data-subscriptions/); [IBKR KB non-pro US data](https://ibkb.interactivebrokers.com/es/tag/market-data?page=2); [Trade Automation Toolbox guide](https://support.tradeautomationtoolbox.com/hc/en-us/articles/43583679288339-Market-Data-Problems-in-IB-Paper-account)
- **IBKR:** The TWS API provides option greeks (model and bid/ask/last computations). — [IBKR TWS API option greeks](https://www.interactivebrokers.com/docs/tws-api/doc/market-data-live/option-greeks/introduction)
- **Schwab:** The Schwab data feed is free for Schwab account holders when used via QuantConnect. — [QuantConnect Schwab dataset docs](https://www.quantconnect.com/docs/v2/cloud-platform/datasets/charles-schwab)
- **Tradier:** A May 2026 third-party aggregator lists real-time market data as included with the $10/mo API plan. The sandbox uses delayed data. — [apispine Tradier](https://apispine.com/tradier); [Tradier docs](https://docs.tradier.com/docs/endpoints)
- **Tradier via QuantConnect:** Options trading requires delayed data from Tradier's data provider. — [QuantConnect Tradier docs](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/tradier)
- **Public.com:** The API exposes option chains. — [Public API](https://public.com/get/api)

### Inferences
- For backtesting options swing strategies with realistic bid/ask, no broker API here is sufficient. Alpaca has only 2.5 years of history and its historical quote endpoint is questionable, and broker APIs generally serve snapshots. Budget for a separate historical vendor (e.g., ThetaData, Polygon/"Massive", Cboe DataShop all showed up in searches), with broker data used only for live signals.
- Low-cost real-time options data: Schwab (free with account) and Tradier (included with plan) beat Alpaca ($99/mo) and IBKR (subscriptions plus a funded-account requirement).

### Gaps
- Exact current IBKR OPRA non-pro monthly fee wasn't captured.
- Whether Alpaca returns greeks/IV in its options snapshot endpoint wasn't confirmed from official docs. Only a third-party MCP server claims it.
- Schwab, Tradier, tastytrade and Webull greeks-via-API details weren't verified. tastytrade streams via DXLink (from prior knowledge, not verified this session).
- Historical options data via Schwab, Tradier, tastytrade and IBKR APIs wasn't researched in depth.

---

## 4. Costs: commissions, per-contract fees, minimums, data/API fees

### Takeaway
Cheapest per contract: Alpaca ($0 commission, pass-through regulatory fees; index options reportedly +$0.50/contract exchange fee), Public ($0 plus rebates), and Tradier Pro ($10/mo for $0 equity options, $0.35 index). tastytrade's $1 to open / $0 to close (capped at $10/leg, caps excluding SPX/XSP) suits swing trading. IBKR Pro is $0.65/contract (tiered). TradeStation advertises "as low as" $0 to $0.60.

### Cited Findings
- **Alpaca:** No commissions for self-directed individual API accounts trading US options. Exceptions: certain partner arrangements, the Elite Smart Router, and non-retail order flow. Regulatory fees: TAF $0.00279/contract (sells), ORF $0.02685/contract, OCC $0.02/contract (capped at $55/trade), plus CAT fees. — [Alpaca options fees support](https://alpaca.markets/support/what-are-the-fees-associated-with-options-trading); [Alpaca regulatory fees](https://alpaca.markets/support/regulatory-fees)
- **Alpaca:** US index options reportedly carry a $0.50/contract fee. This comes from a news article and wasn't confirmed on Alpaca's schedule. — [Finance Magnates](https://www.financemagnates.com/institutional-forex/alpaca-moves-index-options-from-paper-trading-to-live-api-access/)
- **IBKR Pro:** $0.65/contract for premiums of $0.10 or more, up to 10,000 contracts/month, with lower tiers above that. $1.00 minimum per order. Plus ORF $0.02295/contract, sell-side transaction fees, CAT fees, and $1.00/contract for direct-routed orders. IBKR Lite uses a fixed rate for the first 1,000 contracts/month. The trading API is free to all clients. — [IBKR options commissions](https://www.interactivebrokers.com/en/pricing/commissions-options.php?re=amer+); [IBKR KB option commission](https://ibkb.interactivebrokers.com/es/node/1848); [IBKR Web API trading intro](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/)
- **Tradier (rates "as of March 2026"):** Lite (free) charges $0.35/contract on equity and index options, and API access is listed. Pro ($10/mo) charges $0.00 on equity/ETF options and $0.35 on index options. Pro Plus ($35/mo) charges $0.10 on index options, with a $5 assignment/exercise fee vs $9. The fee table also lists an "SPX $0.45/contract" single-listed index fee; whether it stacks with the commission is unclear. — [Tradier pricing](https://tradier.com/individuals/pricing); [Tradier brokerage pricing](https://brokerage.tradier.com/individuals/pricing)
- **tastytrade:** $1/contract to open, $0 to close, capped at $10 per leg. SPX, RUT, VIX, OEX, XEO, DJX and XSP are excluded from the cap. Exchange, clearing and regulatory fees are extra. This comes from third-party 2026 reviews and an older tastytrade cap page; a current official fee page wasn't verified. — [tastytrade capped commissions page](https://info.tastyworks.com/capped); [InvestorMint tastytrade review 2026](https://investormint.com/software-tools/tastytrade-review-2026)
- **TradeStation:** US index options "as low as $0.60/contract." Single- and multi-leg options "as low as $0." A limited-time promo offers $0/leg for new accounts. Older TradeStation pages show conflicting legacy rates ($0.50 above 50 contracts, $1.00 index). — [TradeStation options](https://www.tradestation.com/trading-products/options/); [TradeStation promo](https://www.tradestation.com/promo/options-stars/)
- **TradeStation API minimum:** A third-party vendor claims API keys require a $10,000 account balance. Unverified, and the vendor has a commercial interest. — [PickMyTrade review 2026](https://blog.pickmytrade.io/tradestation-review-2026-best-broker-for-automated-traders/)
- **Schwab:** $0.65/contract per third-party tables. — [TradeAlgo options APIs 2026](https://www.tradealgo.com/trading-guides/options/options-trading-apis-how-to-build-automated-options-strategies-in-2026)
- **Public.com:** The API is free with no commissions, open to all members, and needs no approval. API trades qualify for Public's options rebate of $0.06 to $0.18 per contract based on monthly volume. Personal, non-commercial use only. — [Public API](https://public.com/get/api); [Finder Public review](https://finder.com/public-review)
- **Webull:** Live options require an options application and approval. — [Webull options guide](https://www.webull.com/learn/course/DbpPvC/Guide-to-Trade-Options-on-Webull)

### Inferences
- For swing trading (low turnover), commission differences are small relative to slippage on wide options spreads. A 4-leg iron condor of 1 lot round-trip costs about $0 at Alpaca/Public, about $4 at tastytrade (open only), about $5.20 at IBKR Pro, and $0 at Tradier Pro plus the $10/mo fee (equity options), all plus regulatory fees.
- For SPX specifically, tastytrade's cap exclusion and Tradier's index fees make IBKR and Alpaca relatively competitive. Verify Alpaca's $0.50 index fee.

### Gaps
- Official Schwab, Webull and E*TRADE per-contract options pricing wasn't verified from primary pages.
- Account minimums per broker weren't systematically verified. IBKR needs about $500 for API data and Alpaca has no minimum (per TradeAlgo).

---

## 5. Python tooling, SDK maintenance, rate limits, auth friction

### Takeaway
Best Python ergonomics: alpaca-py (official, active, Aug 2026 release), tastytrade (unofficial but very active, Aug 2026), and Webull's official SDK (Sep 2026). ib_async is the de facto IBKR library (last release Dec 2025) but requires a running TWS/IB Gateway with daily re-auth. schwab-py hasn't released since June 2025, and Schwab's 7-day refresh-token expiry forces a manual browser login weekly. tastytrade's OAuth refresh tokens don't expire, the lowest-friction auth for unattended bots.

### Cited Findings
- **PyPI latest releases, checked 2026-10-07 via PyPI JSON API:** alpaca-py 0.44.0 (2026-08-11); tastytrade 13.2.3 (2026-08-07); webull-openapi-python-sdk 3.0.2 (2026-09-21); ib-async 2.1.0 (2025-12-08); schwab-py 1.5.1 (2025-06-30); nautilus-trader 1.231.0 (2026-08-02). No `tradestation-py` package exists on PyPI. — [PyPI alpaca-py](https://pypi.org/project/alpaca-py/); [PyPI tastytrade](https://pypi.org/project/tastytrade); [PyPI ib-async](https://pypi.org/project/ib-async/); [PyPI schwab-py](https://pypi.org/project/schwab-py/); [PyPI webull-openapi-python-sdk](https://pypi.org/project/webull-openapi-python-sdk/); [PyPI nautilus-trader](https://pypi.org/project/nautilus-trader/)
- **Schwab auth:** Access tokens last 30 minutes. Refresh tokens last 7 days, then a manual browser login is required. The Schwab API team indicated this "might change in the future" with no timeline. One client library notes refresh tokens may be single-use and rotate. — [schwabr CRAN manual](https://stat.ethz.ch/CRAN/web/packages/schwabr/schwabr.pdf); [dp_exchange_schwab notes](https://repo.hex.pm/preview/dp_exchange_schwab/0.1.28/usage-rules.md); [tda_to_schwab GitHub](https://github.com/48n116w/tda_to_schwab)
- **Schwab:** One authenticated account at a time per user, so deploying a second QuantConnect algorithm stops the first. — [QuantConnect forum](https://www.quantconnect.com/forum/discussion/19323/if-i-have-two-different-live-deploy-quant-strategies-can-i-have-them-all-place-orders-within-the-same-single-charles-schwab-securities-account-through-quantconnect/p1)
- **Schwab:** Developer apps have an application-level order rate limit for place/cancel/replace per minute. — [MyLinedChart](https://mylinedchart.com/resources/articles/schwab-api-for-technical-traders-workflow-fit-checklist)
- **IBKR auth:** For retail and individual clients, Web API auth goes through the Client Portal Gateway (a local Java program). OAuth 2.0 (private_key_jwt, direct to api.ibkr.com) is for licensed organizations, advisors and IBrokers only. OAuth 1.0a is for advisors, organizations and third-party services. — [IBKR Web API trading](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/); [IBKR OAuth 2.0 intro](https://www.interactivebrokers.com/docs/web-api/authentication/oauth-2/introduction); [IBKR OAuth 1.0a intro](https://www.interactivebrokers.com/docs/web-api/authentication/oauth-1a/introduction)
- **IBKR 2026 changelog:** Since 2026-03-12, OAuth 2.0 websockets pass the bearer token via a `sessionToken` query param. In Feb 2026, Morningstar ratings trading support and the `/md/regsnapshot` endpoint were retired. — [IBKR Web API changelog 2026-03-12](https://www.interactivebrokers.com/docs/web-api/changelog/2026/3/12); [IBKR Web API changelog](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-changelog/)
- **IBKR:** ib_async/ib_insync is the Python library "almost every developer actually uses" instead of the official ibapi. IB Gateway requires daily restarts and re-authentication, which trips up headless deployments; Docker tooling is a common workaround. Third-party source. — [BrokerListings IBKR API](https://brokerlistings.com/reviews/interactive-brokers/does-interactive-brokers-have-an-api)
- **tastytrade auth:** OAuth2 is required. Access tokens come from exchanging a refresh token at POST /oauth/token. Sandbox and prod credentials are separate. Per the SDK docs, refresh tokens don't expire and access tokens last about 15 minutes, auto-refreshed. Legacy session login was retired (Dec 1, 2024 per a third-party README). — [tastytrade OAuth2 docs](https://developer.tastytrade.com/docs/authentication/oauth2/); [tastytrade SDK sessions docs](https://tastyworks-api.readthedocs.io/en/latest/sessions.html); [tasty-go README](https://github.com/laustindasauce/tasty-go)
- **tastytrade via QuantConnect:** The integration uses a long-lived OAuth token, so deployments "can run for months without re-authentication." — [QuantConnect tastytrade docs](https://www.quantconnect.com/docs/v2/lean-cli/live-trading/brokerages/tastytrade)
- **tastytrade SDK:** The SDK (tastyware/tastytrade) is unofficial and sync/async. Its GitHub repo had 224 stars and 74 forks, last pushed 2026-05-05 per a search snippet; PyPI shows a newer 2026-08-07 release. — [GitHub tastyware/tastytrade](https://github.com/tastyware/tastytrade); [gittrend](https://gittrend.io/repo/tastyware/tastytrade)
- **Webull:** The official unified SDK is `webull-openapi-python-sdk` (webull-inc). Don't mix it with the older split `webull-python-sdk-*` packages. The HK docs require Python 3.8 to 3.11. — [GitHub webull-openapi-python-sdk](https://github.com/webull-inc/webull-openapi-python-sdk); [Webull HK SDK docs](https://developer.webull.hk/apis/docs/sdk)
- **TradeStation:** REST API callable from any HTTP language. Options endpoints are reportedly rate-limited to 90 requests/min (third-party, unverified). — [PickMyTrade review 2026](https://blog.pickmytrade.io/tradestation-review-2026-best-broker-for-automated-traders/)
- **Alpaca:** Algo Trader Plus allows up to 10,000 requests/min. Official SDKs: alpaca-py and alpaca-trade-api-go. An MCP Server V2 exists (June 2026 guide). — [apis.io Alpaca plans](https://apis.io/plans/alpaca-markets/alpaca-markets-plans-pricing/); [Alpaca learn: MCP server](https://alpaca.markets/learn/vibe-coding-how-to-build-options-trading-algorithms-with-alpacas-mcp-server-cursor-ai)
- **E*TRADE:** OAuth 1.0a with separate sandbox and production hosts. — [API Evangelist](https://apis.apievangelist.com/store/etrade)
- **Public.com:** API key generated in Account Settings > Security > API, no approval needed. — [Public API](https://public.com/get/api)

### Inferences
- schwab-py's 15-month gap since its last release, combined with the weekly manual re-login, makes Schwab the highest-friction choice for an unattended bot. Monitor the repo before committing.
- IBKR is the most capable, but expect to run IB Gateway (e.g., via Docker plus IBC) with daily re-auth handling.
- The lowest auth friction for a 24/7 bot is Alpaca (static API keys) and tastytrade (non-expiring refresh token).

### Gaps
- GitHub stars, open-issue counts and last-commit dates couldn't be fetched (GitHub API access blocked in this session). Only the tastytrade snippet figure was available.
- No 2026 confirmation of whether Schwab changed the 7-day refresh window.
- Official rate limits for Alpaca trading (non-data), IBKR (pacing), tastytrade and Tradier weren't verified.
- No E*TRADE Python SDK maintenance status was found.

---

## 6. Reliability, developer reputation, account restrictions (PDT, approval levels, margin)

### Takeaway
The $25k PDT rule is gone. The SEC approved FINRA Rule 4210 amendments (April 14, 2026), effective June 4, 2026, replacing PDT with real-time intraday margin, but brokers may phase in compliance until October 20, 2027. So check each broker's implementation. Third-party rankings favor Alpaca for Python developers and IBKR for capability. No 2026 outage data was found.

### Cited Findings
- **PDT:** The SEC approved FINRA's Rule 4210 amendments on April 14, 2026 (King & Spalding says April 15). They eliminate the PDT designation and the $25,000 minimum, replacing them with intraday margin based on real-time risk. Effective June 4, 2026, with an optional phase-in to October 20, 2027. Repeated unmet intraday deficits can trigger a 90-day freeze on new credit extensions. — [WilmerHale](https://www.wilmerhale.com/en/insights/client-alerts/20260423-sec-approves-amendments-to-finra-rule-4210-replacing-day-trading-margin-requirements-with-a-modernized-intraday-margin-standard); [King & Spalding](https://www.kslaw.com/news-and-insights/finra-adopts-sweeping-changes-to-margin-requirements-for-day-trading); [FINRA weekly notice Jan 2026](https://www.finra.org/compliance-tools/weekly-archive/01072026)
- E*TRADE implemented the new intraday margin rules on June 9, 2026. — [E*TRADE PDT rule change](https://us.etrade.com/knowledge/library/margin/pattern-day-trading-rule-change)
- Webull has published a "PDT Rule Eliminated" explainer. — [Webull blog](https://www.webull.com/blog/321-Understanding-the-PDT-Rule-What-It-Was-Why-It-Changed-and-What-It-Means-Now)
- **Reputation (third-party, affiliate-prone):** Brokerchooser ranks Alpaca #1 for US algo trading in 2026. TradeAlgo calls IBKR's TWS API "the most feature-complete." Foresight Trader highlights tastytrade's single API across stocks, options, futures and crypto. — [BrokerChooser](https://brokerchooser.com/best-brokers/best-brokers-for-algo-trading-in-the-united-states); [TradeAlgo](https://www.tradealgo.com/trading-guides/tools/best-broker-apis-for-algorithmic-trading-in-2026); [Foresight Trader](https://foresighttrader.com/learn/best-us-brokers-api-access-algo-trading)
- **Options approval:** Alpaca live accounts need an approved options level (L3 for multi-leg). Webull requires an options application. — [Alpaca changelog](https://docs.alpaca.markets/us/changelog/multi-leg-level-3-options-trading-in-paper); [Webull options guide](https://www.webull.com/learn/course/DbpPvC/Guide-to-Trade-Options-on-Webull)
- Alpaca reserves the right to charge fees for order flow deemed non-retail. — [Alpaca options fees](https://alpaca.markets/support/what-are-the-fees-associated-with-options-trading)

#### Sub-$25k account: margin vs cash for defined-risk spreads (added per coordinator constraint)
Bottom line from sources: at every broker checked, verticals, iron condors and calendars need a **margin account** (usually the "Level 3"/spread tier). The practical floor is the FINRA/broker **$2,000 margin minimum**, not $25k. Cash accounts are generally limited to long options, covered calls and cash-secured puts.
- **Regulatory basis:** Schwab's options application states that securities regulations confine spread positions to margin accounts. A third-party guide likewise says FINRA expects "almost all option spread transactions" in a margin account. — [Schwab options application APP40015](https://client.schwab.com/secure/file/SERVICE-ACCOUNTSETTINGS-OPTIONSAPPROVALSIRRA-PDFURLS/APP40015-final-fillable.pdf); [TradersPost guide](https://blog.traderspost.io/article/how-much-money-needed-to-trade-options)
- **Alpaca:** All individual accounts are reportedly margin accounts. You can cap buying power to cash with `max_margin_multiplier=1`, and individual cash accounts have "no definite timeline" (forum reply, undated). You need $2,000+ equity for margin and shorting; below $2,000 you're restricted to 1x buying power. Level 3 maintenance is computed as the worst-case payoff (max loss) of the combined position, per expiration, taking the largest across expirations (relevant for calendars), with a "universal spread rule" that can reduce requirements. A forum user reports Alpaca deducted more buying power than the strike-width formula implies. No separate L3 minimum beyond $2k was found. — [Alpaca Options Level 3 docs](https://docs.alpaca.markets/docs/options-level-3-trading); [Alpaca margin docs](https://docs.alpaca.markets/docs/margin-and-short-selling); [Alpaca forum: cash accounts](https://forum.alpaca.markets/t/dan-wheres-the-cash-only-account-option/18353); [Alpaca forum: spread margin](https://forum.alpaca.markets/t/need-clarity-on-margins-while-going-short-option-spreads/16425)
- **IBKR:** No minimum for cash accounts; $2,000 for margin accounts (third-party guide). Iron condor margin = width of one side (short put strike minus long put strike) × 100 × contracts, if IBKR recognizes it as a condor (same underlying and expiry, equal wing widths). Otherwise it's margined as two separate spreads, and margin optimization can change recognition. — [IBKR KB: iron condor margin](https://ibkb.interactivebrokers.com/de/node/600); [TradersPost guide](https://blog.traderspost.io/article/how-much-money-needed-to-trade-options)
- **Tradier:** Option levels: Level 3 = Level 2 + spread permissions. Cash accounts are limited to a narrow set of strategies (covered calls and cash-secured puts visible); all others need margin. Margin minimum $2,000; "no minimums to trade up to level 3 options"; no minimum to open a cash account. — [Tradier option levels](https://support.tradier.com/what-are-the-option-levels-at-tradier-brokerage); [Tradier options accounts FAQ](https://support.tradier.com/kb/guide/en/options-accounts-faq-DleSIPe16S/Steps/4507046); [Tradier minimum funding](https://support.tradier.com/what-are-the-minimum-funding-requirements-at-tradier-brokerage)
- **tastytrade:** Cash accounts have only one trading level. Margin accounts have three levels plus portfolio margin. tastytrade's own guide is titled "Why are Margin Accounts Necessary for Defined-Risk Options Trades?" (the full answer wasn't retrieved). IRAs default to "limited margin," which allows defined-risk spreads. — [tastytrade margin vs cash](https://tastytrade.com/learn/accounts/margin-vs-cash-accounts/); [tastytrade account types](https://tastytrade.com/learn/accounts/account-types/); [tastytrade IRA](https://tastytrade.com/accounts/ira/how-to-open-ira)
- **Schwab:** Spreads require margin. Credit spreads on broad-based indexes require strike difference × 100 × contracts; debit spreads require 100% of cost. IRA spread trading via limited margin reportedly requires $25,000 minimum equity. That applies to IRAs only, from an older document, so verify. — [Schwab margin requirements](https://www.schwab.com/margin/requirements); [Schwab options application](https://client.schwab.com/secure/file/SERVICE-ACCOUNTSETTINGS-OPTIONSAPPROVALSIRRA-PDFURLS/APP40015-final-fillable.pdf)
- **Webull (US):** Cash accounts and IRAs go up to Level 2. Level 3 covers credit and debit spreads, butterflies, iron butterflies, condors and iron condors. Spreads require a margin account, Level 3 approval, and $2,000 minimum start-of-day margin equity. Credit-spread buying power = width × 100 × contracts. — [Webull available options strategies](https://www.webull.com/help/faq/10980-Available-options-strategies); [Webull options buying power](https://www.webull.com/help/faq/657-Options-buying-power)
- **TradeStation:** Publishes an options margin requirements page (contents not retrieved). — [TradeStation options margin requirements](https://tradestation.com/pricing/options-margin-requirements)
- **PDT for a sub-$25k account:** As of June 4, 2026 the FINRA rule no longer imposes the $25k PDT minimum, but brokers may phase in until Oct 20, 2027, so a broker could still enforce legacy PDT logic in the interim. A margin account (required for spreads) was precisely what PDT applied to, so this matters for spread traders. — [WilmerHale](https://www.wilmerhale.com/en/insights/client-alerts/20260423-sec-approves-amendments-to-finra-rule-4210-replacing-day-trading-margin-requirements-with-a-modernized-intraday-margin-standard)

### Inferences
- PDT mattered less for swing trading anyway. Its removal mainly helps sub-$25k accounts that occasionally close same-day. Confirm per broker, since phase-in runs until Oct 2027.
- For a sub-$25k account running verticals, condors and calendars, plan on a **margin account with at least $2,000 equity and Level 3 (spread) approval** at any broker. Keep a cash cushion above $2k so a drawdown doesn't drop the account below the margin threshold (Alpaca reverts to 1x buying power below $2k; Webull checks start-of-day margin equity).
- Margin engines differ. Alpaca and IBKR use max-loss or strategy-recognition logic, and users report surprises (Alpaca over-deducting; IBKR not recognizing condors with unequal wings). Bots should query buying power after each fill rather than assume width × 100.
- Paper accounts at Alpaca automatically get L3 without approval, so live L3 approval can lag. Apply early.
- Spread strategies (condors, verticals) typically need margin accounts and the highest options level at most brokers. Plan approval timelines into the paper-to-live move.

### Gaps
- No 2026 outage reports or incident history was found for any broker (r/algotrading threads didn't come up in search).
- Per-broker PDT implementation dates (beyond E*TRADE) weren't found.
- Per-broker options approval level naming and requirements weren't fully compared (Tradier, Webull and tastytrade levels partially captured above).
- Which brokers still enforce legacy PDT for margin accounts as of Oct 2026 (during the phase-in) wasn't found, except E*TRADE (switched June 9, 2026).
- TradeStation's and E*TRADE's cash vs margin spread rules weren't retrieved. Alpaca's cash-account status is from an undated forum post.

---

## 7. Open-source framework compatibility and QuantConnect cloud routing

### Takeaway
QuantConnect cloud (paid tier) can route options to IBKR, Tradier, Schwab, tastytrade, Alpaca and Webull, and LEAN CLI docs exist for Public. Alpaca, IBKR, tastytrade and Webull integrations cover index options. NautilusTrader is actively released (Aug 2026), and IBKR is its main US-equity-options venue (adapter not verified this session).

### Cited Findings
- **QuantConnect live brokerages with options:** Schwab (equities, options, index options; no paper; one deployment per account; free Schwab data), Tradier (equities and equity options; delayed-data requirement for options; paper lacks streaming), tastytrade (equity, index, futures options; open-source integration; long-lived OAuth), Alpaca (equities, options, crypto; needs a paid Researcher seat plus a live node), Webull (equities, options, index options; recently announced), IBKR. LEAN CLI docs also exist for Public. — [QC Schwab](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/charles-schwab); [QC Tradier](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/tradier); [QC tastytrade](https://www.quantconnect.com/docs/v2/lean-cli/live-trading/brokerages/tastytrade); [QC Alpaca](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/alpaca); [QC Webull announcement](https://www.quantconnect.com/announcements/20912/integration-with-webull-for-equities-options-and-index-option-trading/p0); [QC IBKR](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/interactive-brokers); [QC Public LEAN CLI](https://www.quantconnect.com/docs/v2/lean-cli/live-trading/brokerages/public)
- Live trading on QuantConnect requires a paid subscription, and the LEAN CLI requires a paid organization tier. — [QuantConnect live trading overview](https://www.quantconnect.com/docs/v1/live-trading/overview)
- A QC forum thread asks whether QC lacks options data in live paper trading. This points to a known limitation; details weren't captured. — [QC forum](https://www.quantconnect.com/forum/discussion/19089/live-paper-trading-options-data/)
- Lumibot's Schwab integration says multi-leg option spreads aren't yet implemented. — [Lumibot Schwab](https://lumibot.lumiwealth.com/brokers.schwab.html)
- TradeStation integrates with Tradetron (no-code automation) for multi-leg strategies. — [FX News Group](https://fxnewsgroup.com/forex-news/platforms/tradestation-securities-announces-api-integration-with-tradetron/)
- TradersPost supports Public options (beta, live only, single-leg only). — [TradersPost blog](https://blog.traderspost.io/article/publiccom-traderspost-integration)
- nautilus-trader 1.231.0 was released 2026-08-02. — [PyPI nautilus-trader](https://pypi.org/project/nautilus-trader/)

### Inferences
- If you want QuantConnect/LEAN end to end (backtest with QC's historical options data, then paper, then live), IBKR or tastytrade are the strongest fits: index options, real paper (IBKR) or long-lived auth (tastytrade). Alpaca works too but requires paid QC tiers. Schwab's lack of paper and its one-deployment limit are drawbacks.
- backtrader is effectively unmaintained (from general knowledge, unverified this session) and has weak options support. Prefer LEAN or NautilusTrader for options.

### Gaps
- NautilusTrader adapter list (IBKR confirmed from prior knowledge; Alpaca/tastytrade/Tradier adapters not verified) and options support depth weren't checked this session.
- backtrader maintenance status wasn't verified (GitHub blocked).
- QuantConnect's TradeStation and E*TRADE support status wasn't found.

---

## 8. Synthesis: which platform for a solo Python dev doing backtest, then paper, then live options swing trading

### Takeaway
Under the user's constraints (<$25k, defined-risk multi-leg only), every viable broker needs a margin account with at least $2k and Level 3 (spread) approval. The PDT $25k rule was eliminated effective June 4, 2026, though brokers may phase in until Oct 2027. Shortlist: (1) **Alpaca** for the simplest Python path. Free paper with multi-leg, $0 commissions, live SPX/XSP, active SDK. Downsides: $99/mo for real OPRA data, history only from Feb 2024, no index data. (2) **IBKR** for maximum capability and paper realism (real prices, $1M paper account, greeks, every product). Downsides: Gateway/TWS ops burden, daily re-auth, data subscriptions, $0.65/contract. (3) **tastytrade** for low-friction auth and options-native pricing, but its sandbox is weak. **Tradier** is a solid low-cost REST alternative. **Schwab** is not recommended for automation (no paper, 7-day re-auth, stale SDK). **Webull** and **Public** are promising but less proven.

### Cited Findings
(All supporting citations appear in sections 1 to 7. Key ones:)
- Alpaca: multi-leg in paper and live, index options live, $0 commission, $99/mo OPRA, history since Feb 2024 — [Alpaca changelog](https://docs.alpaca.markets/us/changelog/multi-leg-level-3-options-trading-in-paper); [Alpaca index options blog](https://alpaca.markets/blog/alpaca-launches-index-options-via-trading-api); [Alpaca historical option data](https://docs.alpaca.markets/docs/historical-option-data)
- IBKR: paper uses real market prices and sizes — [IBKR KB 1719](https://ibkb.interactivebrokers.com/article/1719); retail must use the Client Portal Gateway — [IBKR Web API](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/)
- tastytrade: non-expiring refresh token; sandbox resets every 24h with no fill control — [tastytrade SDK docs](https://tastyworks-api.readthedocs.io/en/v12.4.0/paper.html)
- Schwab: no paper — [QC Schwab](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/brokerages/charles-schwab); 7-day refresh token — [schwabr](https://stat.ethz.ch/CRAN/web/packages/schwabr/schwabr.pdf); schwab-py last released 2025-06-30 — [PyPI](https://pypi.org/project/schwab-py/)

#### Comparison matrix for the user's constraints (<$25k, defined-risk multi-leg only: verticals, iron condors, calendars)
Each cell summarizes the cited findings above. "?" means not verified.

| Broker | Multi-leg via API (verticals / condors / calendars) | Paper/sandbox supports multi-leg? | Spread account req. (<$25k) | Options commission | Python SDK (latest PyPI) | Auth friction |
|---|---|---|---|---|---|---|
| Alpaca | Yes. Spreads, iron condors, calendars explicitly listed; POST /orders (live since Feb 2025) | Yes. L3 automatic in paper; multiple paper accounts | Margin (all accounts are margin); $2k for >1x; L3 approval | $0 + reg fees; index reportedly +$0.50/ct | alpaca-py 0.44.0 (2026-08-11), official | Low (API keys) |
| IBKR | Yes. Combo/BAG orders (prior knowledge); index options | Yes. $1M paper at real prices and sizes; needs data sharing | Margin $2k; condor margin = one wing width if recognized | $0.65/ct Pro (tiered), $1 min | ib_async 2.1.0 (2025-12-08), community | High (Gateway, daily re-auth) |
| tastytrade | Yes. Native multi-leg; index options | Weak. Sandbox resets 24h, limited symbols, no fill control; paid 3rd-party paper API | Margin (cash = 1 level); IRA limited margin allows defined risk | $1 open / $0 close, $10/leg cap (SPX/XSP excluded) | tastytrade 13.2.3 (2026-08-07), unofficial | Low (non-expiring refresh token) |
| Tradier | Yes (Level 3 spreads); QC supports equity options | Yes, but delayed data; QC paper lacks streaming | Margin $2k; L3 = spreads | Pro $10/mo: $0 equity, $0.35 index (+SPX fee?) | ? (no SDK checked) | Low (static token) |
| Schwab | Yes, but undocumented JSON; 4-leg reported working | **No paper** | Margin; IRA spreads reportedly need $25k | ~$0.65/ct (3rd-party) | schwab-py 1.5.1 (2025-06-30), stale | High (7-day manual re-login) |
| Webull | Yes. `order option strategy` (US); index options unclear | Yes. OpenAPI paper since Jul 21 2026, multi-leg claimed | Margin $2k + L3 | ? | webull-openapi-python-sdk 3.0.2 (2026-09-21), official | ? |
| TradeStation | Reportedly yes (3rd-party) | SIM exists; multi-leg unverified | ? (margin page exists) | "as low as" $0 / $0.60 index | none on PyPI | ?; API key reportedly needs $10k (unverified) |
| E*TRADE | Option chains + orders; multi-leg unverified | Sandbox returns canned responses (not a simulator) | ? | ? | none checked | OAuth 1.0a |
| Public | Yes. Multi-leg strategies per Public API page | No paper found | ? | $0 + $0.06–0.18/ct rebate | ? | Low (API key) |

### Inferences
- **Under the new constraints (<$25k, defined-risk spreads), Alpaca is the most straightforward fit.** It has explicit API support for verticals, condors and calendars; free paper with multi-leg on by default; $0 commissions; a $2k margin threshold; and the least auth friction. Main caveats: $99/mo for real-time OPRA (indicative data is unsuitable for pricing spreads live), and reports of conservative buying-power deduction on spreads.
- **IBKR is the best choice if paper-fill realism for spreads matters most**, at the cost of operational complexity and data subscriptions.
- **tastytrade** has good economics for swing spreads (closing is free) and painless auth, but its weak sandbox breaks the "paper with the same code" step unless you pay for the third-party paper API or paper-trade via QuantConnect.
- **Schwab is a poor fit** for a paper-first workflow: no paper, undocumented multi-leg schema, weekly re-auth.
- A pragmatic architecture: backtest with a third-party historical options dataset (or QuantConnect's), paper on Alpaca or IBKR, then go live on the same broker to avoid order-schema rewrites.
- For SPX/XSP specifically (European, cash-settled, Section 1256 tax treatment noted by Alpaca), IBKR and Alpaca are the cleanest. Alpaca needs an external SPX index feed.

### Gaps
- No hands-on fill-quality comparison (paper vs live slippage) across brokers exists in the sources found.
- E*TRADE and TradeStation are under-researched relative to the others due to sparse 2026 primary sources.
