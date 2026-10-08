# Free and cheap historical options data: verified survey (2026-10-08)

A Sonnet research agent ran this survey with open web access. **VERIFIED** means the agent fetched the page, API or data itself. **UNVERIFIED** means the fact comes from a search snippet or a secondhand source. The sample files were downloaded to the session scratchpad and are not kept.

## Bottom line
No free source covers 2018 to 2025 with dense SPY chains, bid/ask and greeks. The best pieces:
- **OptionsDX EOD** is free for SPY, SPX, QQQ and VIX, 2010 to 2023. It stops at Dec 2023.
- **Alpha Vantage Premium** for one month ($49.99) covers 2008 to yesterday.
- **A Kaggle SPY dataset** (2014–2025) may be an Alpha Vantage re-upload. It needs a Kaggle login to check.

## Ranked shortlist

**1. OptionsDX EOD (score 4/5).** https://www.optionsdx.com/product/spy-option-chains/
- **Access:** a free account, then a $0 checkout (VERIFIED, FAQ). Files are monthly CSVs delivered through ShareFile. The login expires 100 days after purchase, so download promptly.
- **Prices** (VERIFIED, from the shop's public Store API; IWM is not offered):

| Ticker | EOD | 15-min (includes 15:45 ET) | Minutely |
|---|---|---|---|
| SPY | $0, 2010–2023 | $5/yr, 2016–2023 | $50/yr, 2018–2023 |
| SPX | $0, 2010–2023 | $5/yr, 2016–2023 | $50/yr, 2019–2023 |
| QQQ | $0, 2012–2023 | $5/yr, 2016–2023 | none |

- **Columns** (VERIFIED, vendor sample `spy_sample-1.csv`): `QUOTE_UNIXTIME, QUOTE_READTIME, QUOTE_DATE, QUOTE_TIME_HOURS, UNDERLYING_LAST, EXPIRE_DATE, EXPIRE_UNIX, DTE, C_DELTA, C_GAMMA, C_VEGA, C_THETA, C_RHO, C_IV, C_VOLUME, C_LAST, C_SIZE, C_BID, C_ASK, STRIKE, P_BID, P_ASK, P_SIZE, P_LAST, P_DELTA, P_GAMMA, P_VEGA, P_THETA, P_RHO, P_IV, P_VOLUME, STRIKE_DISTANCE, STRIKE_DISTANCE_PCT`. This is a wide layout: one row per strike, calls and puts side by side.
- **Density** (VERIFIED, sample of 2020-03-06): 4,858 strike rows across 38 expiries. Within 30–45 DTE: 5 expiries, with 62 calls and 66 puts between 15 and 35 delta, all with bid above 0.
- **Unverified points:**
  - The EOD files themselves; the agent did not register.
  - The 16:00 snapshot time, which comes from a Kaggle mirror's description.
  - The terms. The page only says "sales final" and grants no redistribution rights.
- **Known caveat** (UNVERIFIED, from the David Arias blog): on gap days the EOD data can have a stale underlying. On 2018-02-05 call IV was 33.9% against put IV of 18.3%. Prefer the OTM side and filter out wide spreads.

**2. Alpha Vantage Premium, one month (score 4/5).** https://www.alphavantage.co/documentation/
- **Access:** REST call `function=HISTORICAL_OPTIONS&symbol=SPY&date=YYYY-MM-DD&datatype=csv`. Each call returns one full chain for one date, for any date after 2008-01-01 (VERIFIED).
- **Price:** $49.99/month for 75 requests/min (VERIFIED). One ticker's full history is about 4,700 calls, or roughly an hour.
- **Columns** (VERIFIED, from the IBM demo): `contractID, symbol, expiration, strike, type, last, mark, bid, bid_size, ask, ask_size, volume, open_interest, date, implied_volatility, delta, gamma, theta, vega, rho`.
- **Gaps:** there is no underlying price column, and the snapshot time is not stated.
- **Terms** (VERIFIED, ToS): personal and non-commercial use only.

**3. Kaggle `shankerabhigyan/s-and-p500-options-spy-implied-volatility-2019-24` (score 3/5, possibly 5).**
- **What it is** (VERIFIED via the unauthenticated API): 8.69 GB, labelled CC0, updated 2026-07-26, covering SPY 2014–2025.
- **Likely source:** its columns match Alpha Vantage exactly, so it is probably a re-upload (inferred). That makes the CC0 label doubtful.
- **Content is unverified:** downloading needs a free Kaggle login.

**4. historicaloptiondata.com L2 EOD (score 3/5).** https://historicaloptiondata.com/product/allspy/
- **Prices** (VERIFIED): full SPY history, 2005 to 2026-09, costs $455. Spans under 5 years cost $3.85/month, by email request.
- **Columns** (VERIFIED, from sample `Sample_L2_20190815.zip`): `UnderlyingSymbol, UnderlyingPrice, Exchange, OptionSymbol, Blank, Type, Expiration, DataDate, Strike, Last, Bid, Ask, Volume, OpenInterest, IV, Delta, Gamma, Theta, Vega, Alias`.
- **Snapshot and density** (VERIFIED): the snapshot is stamped 16:00. On 2019-08-15 SPY had 6,952 contracts across 33 expiries.

**5. Databento free credit (score 3/5, UNVERIFIED).**
- **Offer:** $125 of credit that expires in 6 months; a payment method is required.
- **Data:** OPRA `cbbo-1m` (1-minute consolidated best bid and offer) from 2013. No greeks or IV, and no underlying price.
- **Cost:** check per dataset with `metadata.get_cost`, which is free.

## Validation samples (single days, VERIFIED)
- **Cboe DataShop sample** (https://datashop.cboe.com/download/sample/217): SPY on 2023-08-25. Columns include `bid_1545/ask_1545`, `underlying_bid/ask_1545` and `delta_1545`, with 7,630 contracts. This is the gold standard.
- **historicaldata.net sample** (https://historicaldata.net/options.html): SPY on 2022-09-15, 8,202 contracts, columns including `underlying_close` and greeks. The paid archive is $590 one-time for 2002 onward.

## Ruled out
- **philippdubach/options-dataset-hist** (and the claimed copy): does not exist.
- **Brokers:** Alpaca has bars and trades from Feb 2024 only, with current chains. Tradier has OHLC only per known OCC symbol. Interactive Brokers has no expired options. Yahoo/yfinance has current chains only.
- **Other data services:**
  - MarketData.app free tier: 1 year of history, and each contract costs a credit.
  - FlashAlpha: $1,199/month.
  - EODHD: about 1 year of history.
  - Nasdaq Data Link: no free options set.
  - Stooq: no options data.
- **Hugging Face / Kaggle derivatives:** IV summaries, synthetic surfaces, or bar data only.
- **Zenodo, Dataverse, Figshare and Reddit:** nothing usable found.
- **DoltHub** (rechecked):
  - SPY coverage: weekly-ish snapshots 2019 to mid-2024, then daily from about Sep 2024, with 66–210 contracts per day across 3–4 expiries and irregular strikes. No underlying price.
  - The Hugging Face mirror `siddharthmb/stocks-options` (9.13 GB) has the same data.
