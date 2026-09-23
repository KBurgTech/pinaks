# Draft invoice calculation policy

All monetary calculations use `Decimal`; EUR amounts are rounded to two decimal places with `ROUND_HALF_UP`. Quantity has up to four decimal places. Unit price, tax rate, and percentage discount have two decimal places. Quantity must be positive; price may be zero; discount is between 0 and 100 percent.

For each line, multiply quantity by unit price and apply the percentage discount before rounding. With **net entry**, round that discounted net amount, then calculate and round tax on the rounded net. Gross equals net plus tax. With **gross entry**, round the discounted gross amount, divide it by one plus the tax rate and round net; tax is gross minus net. A zero-rate exempt line has zero tax.

Invoice subtotal and tax total sum the already rounded line net and tax amounts. Tax breakdowns group those amounts by category and rate without rounding again. Grand total is subtotal plus tax total. The backend service is authoritative; API clients cannot provide totals. Invoice and line balance equations are also database constraints.
