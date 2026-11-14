# gex-tool

A small Python script that estimates gamma exposure (GEX) levels for the Nasdaq-100
from Cboe's free, delayed option-chain data. No API key and no dependencies beyond
Python 3.

## Run it

```
python gex_pull.py NDX --futures-price 28034.75
python gex_pull.py QQQ --futures-price 28034.75
python gex_pull.py NDX --max-days 7
```

`--futures-price` maps the levels onto NQ futures by scaling with the futures/spot ratio.

## Output

- Console summary: net GEX, call wall, put wall, gamma flip, top strikes
- `gex_<SYMBOL>_<time>.csv`: per-strike call/put GEX and open interest
- `gex_<SYMBOL>_<time>.html`: bar chart of net GEX by strike

## Notes

- Data comes from Cboe's public delayed-quote JSON (about 15 minutes delayed). The endpoint
  is undocumented and may change.
- Open interest updates once per day, so levels reflect the prior close's positioning.
- Calls are treated as positive gamma and puts as negative (a dealer-positioning
  assumption). The results are estimates, not trading signals.
- Not investment advice. Personal use only; check Cboe's terms before anything else.
