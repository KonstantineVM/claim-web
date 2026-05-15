# Regulatory Arbitrage in U.S. Life Insurance

*A reading of FSR Figures 4.9 and 4.10 as a single signal, and what the dashboard should compute*

---

## 1. The phenomenon

A material and growing share of the U.S. life insurance sector is performing bank-shaped maturity transformation — funding long-duration illiquid assets with short-duration runnable liabilities — through a network of intermediaries that spans insurance, banking, money market, and offshore reinsurance regulatory regimes. No single regime supervises the activity end-to-end. Each regime sees only its own slice and finds that slice compliant.

This is the regulatory arbitrage. It is not bilateral (one entity exploiting one regime). It is a network arbitrage in which banks, money market funds, the Federal Home Loan Bank system, life insurers, alternative asset managers, and offshore reinsurance affiliates each play roles that are individually rational, individually supervised, and collectively produce a maturity-transformation and capital-relief chain that no individual regulator measures.

The structural choice that enables the chain on the insurer's funding side is the classification of certain wholesale funding instruments — funding agreements, securities lending cash collateral, FHLB advances, repo — as *insurance reserves* or *operating leverage* rather than as debt. Once classified that way, the activity is governed by insurance regulators who do not compute liquidity coverage ratios, do not run funding-stress tests, and do not have access to a lender of last resort to backstop a run. The complementary choice on the bank side is the inclusion of insurer wholesale funding (in the form of FABNs and similar instruments) as eligible High-Quality Liquid Assets under the Liquidity Coverage Ratio framework, which treats these holdings as if they were genuinely liquid in stress. The further choice on the capital side is the cession of U.S. annuity and funding-agreement liabilities to affiliated offshore reinsurers in Bermuda, the Cayman Islands, or similar jurisdictions, where capital regimes recognize excess spread up-front and require lower reserves against the same liability. The bank LCR rule sees a liquid HQLA buffer; the U.S. insurance regulator sees a stable policyholder reserve (post-cession); the offshore regulator sees a well-capitalized reinsurer under its own rules; the same dollar appears, simultaneously, as all three — which it cannot economically be.

The May 2026 FSR Figures 4.9 (non-traditional liabilities, $531B and growing 15% YoY real) and 4.10 (illiquid asset share, 37% of life insurer general account) are not two parallel signals. They are two faces of one signal: long illiquid asset book on one side, short runnable liability book on the other, growing in parallel, intermediated by a bank-MMF-FHLB network and amplified by a parallel offshore-reinsurance capital-relief channel — whose regulatory regimes cannot see the mismatch in aggregate.

---

## 2. The chain

The arbitrage is not a bilateral relationship between an insurer and a saver. It is a *network* of regulatory regimes — money market regulation, banking regulation, insurance regulation, and offshore reinsurance regimes — used in combination to do collectively what no single regime would permit. Banks appear at multiple points in the network, not as bystanders but as active intermediaries who themselves benefit from the arbitrage. Private-equity-affiliated insurers extend the same logic to the capital side by ceding US liabilities to offshore reinsurance vehicles operating under lighter regimes in Bermuda, the Cayman Islands, or similar jurisdictions.

### 2.1 The funding channels into the insurer

The four FSR Figure 4.9 components correspond to four distinct funding channels, three of which pass through bank intermediaries. A fifth channel — offshore reinsurance — does not bring new cash into the insurer but achieves an analogous arbitrage on the capital side by transferring liabilities (and the reserves backing them) to a more lightly regulated entity, freeing capital for further deployment into the same illiquid asset book.

```
Channel A — Funding-Agreement-Backed Securities (FABS)
    Money market fund investor / Bank HQLA buyer
        ↓ wants short-dated, "liquid", high-quality holding
    Money market fund (Rule 2a-7) / Bank treasury (LCR HQLA portfolio)
        ↓ cannot hold insurance contracts directly; needs a tradeable security
    FABN
        ↓ tradeable security; AAA-equivalent rating from the SPV wrapper
    SPV (bankruptcy-remote passthrough)
        ↓ holds one asset — the funding agreement — and one liability — the FABN
    Funding agreement (classified as policyholder reserve)
        ↓
    Life insurer

Channel B — FHLB Advances
    Capital markets investors in FHLB consolidated obligations
        ↓ wants GSE-backed, short-to-medium-dated paper
    Federal Home Loan Bank (member-owned GSE; effectively a wholesale bank)
        ↓ lends advances to members against pledged collateral
    FHLB advance (classified as "operating leverage" not debt when used for spread lending)
        ↓
    Life insurer (member of FHLB system)

Channel C — Repurchase agreements
    Dealer bank (acting on its own book or for prime brokerage clients)
        ↓ takes pledged securities; provides overnight or short-term cash
    Repo counterparty position
        ↓
    Life insurer (uses cash to invest in spread-lending assets)

Channel D — Securities lending cash collateral
    Dealer bank or custodian bank (running a sec-lending program)
        ↓ borrows securities from the insurer's portfolio in exchange for cash collateral
    Cash collateral on the insurer's balance sheet
        ↓ insurer reinvests in spread-lending portfolio
    Life insurer

Channel E — Offshore reinsurance (capital-side arbitrage)
    US life insurer (state-regulated; subject to NAIC RBC and statutory accounting)
        ↓ cedes blocks of annuity/funding-agreement liabilities to an affiliated offshore reinsurer
    Affiliated offshore reinsurer (typically Bermuda or Cayman; lighter capital regime; books excess spread up-front)
        ↓ holds the reinsured liabilities under offshore statutory rules
    Reduced US-statutory reserve requirement at the ceding US insurer
        ↓ frees capital, allowing more annuity sales / spread-lending capacity
    Life insurer (US legal entity; same illiquid asset book, now larger)
```

The terminal node on every channel is the same: cash arrives at the insurer, which deploys it into the illiquid asset book — CRE loans, private credit, alternatives, illiquid corporate debt, securitized illiquid debt. The same illiquid-asset categories the FSR plots in Figure 4.10.

### 2.2 Banks, asset managers, and offshore reinsurers in the network

The network contains three classes of intermediary, each with its own role and its own captured rent:

**Banks as funder (Channel A).** Bank treasuries hold FABS as part of their HQLA portfolio under the Liquidity Coverage Ratio rule. The FABN qualifies because it is a security with a money-market profile, rated AAA via the SPV wrapper, with an explicit put feature. From the bank's regulatory perspective, the FABN is a Level 2A or Level 2B liquid asset. From the underlying economics, it is a claim on an insurer's illiquid asset book.

**Banks as intermediary (Channels B, C, D).** Dealer banks provide repo and securities-lending services to insurers. The FHLB system is itself a quasi-bank — funded in capital markets, lending to members — that intermediates between the public bond market and life insurer borrowers. Banks earn intermediation spread on each of these channels and do not bear the residual maturity-transformation risk that accumulates at the insurer.

**Alternative-asset-manager-affiliated insurers as integrated operators (intensifies Channels A-D and operates Channel E).** Since the mid-2010s, large alternative asset managers — Apollo, Blackstone, KKR, Brookfield, Carlyle, and others — have acquired or built U.S. life insurers (Athene, Global Atlantic, F&G, American Equity, etc.) and use the annuity flow as funding for their private credit and CLO businesses. The integration produces a closed loop: the insurer issues annuities and NTL on the right side of the balance sheet; the affiliated asset manager originates and structures the illiquid assets on the left side; the same parent earns annuity-business returns *and* asset-management fees on the same dollars; and the structure routinely cedes the insurance liabilities to an offshore affiliated reinsurer to reduce the capital required. PE-affiliated U.S. life and retirement assets reached roughly $900 billion by 2025, and Athene's allocations show the asset-side concentration directly — about 20% of portfolio in ABS, more than half of which is CLOs, vs industry averages of 7% ABS and 2.6% CLOs.

**Offshore reinsurers (Channel E).** The offshore affiliate operates under Bermuda's Economic Balance Sheet framework or Cayman's prescribed regime. Both allow excess spread on annuity liabilities to be recognized as up-front profit and reduce the reserve required against a given liability relative to U.S. statutory accounting. U.S. insurer cessions to Bermuda grew from approximately $205 billion in 2014 to roughly $928 billion in 2024 by the most commonly cited industry figures. The cession does not change the underlying economics of the U.S. policyholder obligation but does change *which regulator measures what reserve* — pushing a fraction of the system's capital adequacy out of U.S. supervisory view.

### 2.3 What each party gets and gives

| Party | Receives | Gives | Bears |
|---|---|---|---|
| MMF investor / bank HQLA buyer | Cash-equivalent yield, par redemption / LCR credit | Cash | Par-break risk if FABN can't be sold |
| Money market fund | Eligible holding paying competitive yield | Cash, Rule 2a-7 monitoring | Run risk if investors redeem en masse |
| Bank treasury (FABN holder) | HQLA-eligible asset paying above true-liquid yield | Cash, regulatory LCR slot | Discovery in stress that "HQLA" is not liquid |
| SPV | Fee, passthrough income | Issues FABN, holds funding agreement | (Passthrough — bears nothing economically) |
| Dealer bank (repo / sec-lending) | Intermediation fee, balance-sheet utilization | Cash or pledged securities, short-term commitment | Counterparty risk to insurer if insurer cannot return collateral |
| FHLB | Member fees, spread on advances | Advance against pledged collateral | GSE implicit-guarantee risk transferred to U.S. taxpayer |
| PE-affiliated asset manager | Asset-management fees + annuity-business returns + CLO-structuring fees on same dollars | Originates the illiquid assets the insurer holds | Reputation and franchise risk if affiliate insurer fails |
| Affiliated offshore reinsurer | Reinsurance premium, accounting treatment of excess spread as up-front profit | Reinsurance coverage under offshore statutory rules | Same policyholder obligation as ceded by U.S. insurer, now booked under lighter capital regime |
| U.S. ceding insurer | Reduced required reserve, freed capital | Cedes liability + reserve to affiliated offshore reinsurer | Same policyholder obligation if offshore affiliate fails or is recaptured |
| Insurer (end of funding chain) | Long-classified funding at money-market cost | Funding agreement / advance / repo / sec-lending obligation | Liquidity mismatch under stress |

### 2.4 Why each party is rational in isolation

- The **MMF investor and bank HQLA buyer** treat the FABN as a short-dated AAA security because that is what it trades like and that is what its rating says.
- The **money market fund** holds it because Rule 2a-7 admits securities, not insurance contracts, and the FABN is a security.
- The **bank treasury** holds it because the LCR framework's HQLA categories admit it, and within those categories the FABN pays more than true-liquid alternatives like Treasury bills.
- The **dealer bank** does repo and sec-lending with the insurer because the insurer is a high-quality counterparty under normal conditions and the intermediation generates fees.
- The **FHLB** lends to the insurer because the insurer is a member, the collateral is acceptable, and the spread between FHLB's bond-market funding cost and the rate charged to the member is positive.
- The **SPV** exists because it converts an insurance contract into a security — a regulatory wrapper that resolves the format mismatch between what the insurer can issue and what bank/MMF buyers can hold.
- The **PE-affiliated asset manager** acquires or builds an insurer because the integration captures asset-management fees, annuity-business spread, and CLO/private-credit structuring fees on the same dollars; from the asset manager's perspective, the captive insurer is a permanent-capital vehicle that lets it deploy private credit at scale.
- The **affiliated offshore reinsurer** accepts cessions because the offshore statutory framework allows a lower reserve against the same liability than U.S. statutory accounting would require, and because the affiliate relationship means the apparent risk transfer keeps the economic exposure inside the same corporate group while the capital benefit accrues to the ceding entity.
- The **U.S. ceding insurer** cedes liabilities offshore because the resulting reduction in required reserves frees capital that can fund additional annuity sales, additional spread lending, or shareholder returns; from the U.S. legal entity's perspective, the reinsurance contract is a legally valid risk transfer to an admitted reinsurer.
- The **insurer** issues funding agreements, takes FHLB advances, does repo, and lends securities because the proceeds are accounting-classified as long-duration insurance liabilities (or as operating leverage not debt) and so do not trigger bank-style liquidity ratios — while the funds themselves can be deployed into spread-earning illiquid assets.

Each party is rational. Each regulatory regime, looking only at the entity it supervises, sees acceptable behavior. The bank's HQLA looks adequate. The MMF's holdings look 2a-7-compliant. The FHLB's advances look collateralized. The U.S. insurer's liabilities look like policyholder reserves (post-cession). The Bermuda reinsurer's books look adequate under Bermuda accounting. The system in aggregate is doing bank-shaped maturity transformation, with the capital adequacy of a fraction of it housed in a regime that no U.S. financial-stability authority directly supervises.

### 2.5 Why the bridge holds, and how it breaks

The bridge holds in normal times because (i) MMF investors and bank treasuries are not all redeeming or selling FABS at once; (ii) dealer banks continue to roll repo and sec-lending; (iii) FHLB continues to advance against pledged collateral; (iv) the insurer's asset book continues to generate returns matching its funding cost; (v) the offshore reinsurer's host jurisdiction continues to admit current capital treatment without retroactive change, and offshore affiliates remain solvent against the ceded liabilities. All five conditions must hold for the arbitrage to be silent.

The bridge breaks when any of the bank intermediation channels withdraws — not only when end-investors run. This happened in March 2020 when dealer banks pulled back from repo intermediation and prime money markets experienced redemptions; insurers had to draw on FHLB advances aggressively as backup, and stable value GICs experienced visible stress. The breaking mechanism is general: when any bank intermediary in the network steps back, the chain compresses onto the remaining channels, which become brittle. The insurer is the residual bearer because the cash demand passes through every intermediary and stops at the entity that holds the illiquid asset book.

Channel E introduces a parallel breaking mode that does not require any of the funding channels to compress. If an offshore jurisdiction changes its capital regime (Bermuda's BMA has tightened multiple times under FSOC, NAIC, and international pressure), if rating agencies reclassify affiliate reinsurance as inadequate risk transfer, or if the offshore reinsurer experiences capital strain from the underlying asset performance, the U.S. ceding insurer faces a *recapture* event — the ceded liabilities and required reserves return to the U.S. balance sheet, and the capital relief that funded the asset accumulation suddenly reverses. This propagates back through the funding channels: a recapture forces the U.S. insurer to find additional capital or to deleverage, which in turn pressures the asset book, which in turn pressures every funding counterparty in Channels A-D.

The maturity transformation is real. The entity that ultimately bears its consequences is the insurer. But the *machinery* of the transformation is a multi-party network in which banks earn intermediation rent at each step, alternative asset managers earn integration rents on both sides of the balance sheet, offshore reinsurers earn cession premiums, and the insurer accumulates the residual risk. The regulator overseeing the U.S. insurer does not measure that residual risk because the network spans regulatory regimes that do not share data on each other's books and includes nodes (the offshore reinsurer) that the U.S. regulator has no direct authority over.

---

## 3. Why every node in the network is opaque to standardized disclosure

The arbitrage works because the accounting classification matches the regulatory regime at each node in the chain. The same classification choices that enable the activity also determine what surfaces in standardized public disclosure and what does not. Every node is partially opaque in a way that is consistent with the *regulatory frame applied to that node*, and the opacity is what allows the activity to be done in plain sight without any single observer seeing the network as a whole.

**On the insurer side (liability classification).** Funding agreements appear inside the "Policyholder Account Balances" line on the balance sheet — alongside actual insurance policy reserves — with no top-level us-gaap tag that distinguishes them. MetLife discloses its funding-agreement aggregate ($66B at 2025-09-30) only as a dimensioned sub-component of PAB, using a custom `met:CapitalMarketsInvestmentProductsAndStableValueGICsMember` axis. FHLB advances, when used for "spread lending" (i.e., this same arbitrage activity), are explicitly classified as *operating leverage rather than debt* per NAIC guidance, and so do not appear in the Long-term Debt note (Note 14 of MetLife's Q3 2025 10-Q contains no FHLB section at all). The FABN itself sits on an SPV that may not be consolidated; it does not appear in MetLife's Note 21 (Contingencies, Commitments and Guarantees). Repo and securities lending cash collateral *do* appear as balance sheet line items, but under different tag names at different insurers — PRU uses the standardized us-gaap tag `SecuritiesSoldUnderAgreementsToRepurchase`; MET uses `PayablesForCollateralUnderSecuritiesLoanedAndOtherTransactions` which combines repo with sec-lending and other collateral payables.

**On the bank side (HQLA classification).** Bank LCR disclosures report HQLA in three buckets — Level 1, Level 2A, Level 2B — without breaking out which fraction of each bucket is true-liquid (Treasuries, Fed reserves) and which fraction is credit-claim instruments that depend on functioning markets. FABS holdings sit inside the bank's Level 2A or Level 2B bucket along with corporate bonds and other credit-claim HQLA. The bank's quarterly Pillar 3 disclosure and FFIEC Y-9C filings report aggregate HQLA but not the composition by underlying counterparty type. From outside the bank, one cannot determine what fraction of the bank's stated "liquid asset buffer" is in fact a claim on an insurer's illiquid asset book through the FABS+SPV wrapper. The bank's regulator sees an LCR-compliant balance sheet; the insurer's regulator sees a PAB-classified policyholder reserve; both regulators are looking at the same underlying economic exposure with different accounting labels.

**On the FHLB side (advance classification).** Federal Home Loan Bank advances to insurer members are disclosed in FHLB consolidated obligations and member-balance reports, but the advance is reported at the level of advance-by-member, not advance-by-purpose. The FHLB does not classify advances by whether they fund spread-lending arbitrage versus genuine liquidity needs. The same FHLB advance can appear on the insurer's books as "operating leverage" (per NAIC) and on FHLB's books as a normal collateralized advance — neither classification captures that the proceeds are deployed into illiquid spread-lending assets rather than held as liquidity buffer.

**On the offshore reinsurance side (jurisdictional boundary).** U.S. statutory filings disclose reinsurance ceded by counterparty on Schedule S of the NAIC annual statement, including affiliate vs non-affiliate classification and the jurisdiction of the assuming reinsurer. The reinsurance ceded is therefore *measurable* from origin data at the U.S.-insurer level — one can identify how much of a U.S. insurer's liabilities have been ceded to Bermuda affiliates and similar. What is *not* measurable from public U.S. data is the offshore reinsurer's asset book, its actual reserves under offshore statutory rules versus what they would be under U.S. statutory rules, or the affiliated relationships that determine whether the reinsurance constitutes genuine risk transfer or accounting-only restructuring. The U.S. ceding-insurer disclosure provides the *amount* ceded; the offshore regime governs everything that happens after the cession, and its disclosures are typically not available through SEC EDGAR or any equivalent U.S. machine-readable source. The opacity is cross-jurisdictional rather than tag-level: the data exists somewhere, but no U.S. authority has consolidated visibility.

**On the asset side (insurer illiquid-asset classification).** The category "illiquid" is not an XBRL classification. Insurers report investments by us-gaap asset type (mortgage loans, real estate, fixed maturity AFS, other limited partnership interests, other invested assets) which cuts across the liquidity dimension. The FSR's six-category illiquid-asset decomposition (other ABS, CRE loans, CRE loans securitized, alternatives, illiquid corporate debt, illiquid corporate debt securitized) is an *analytical overlay* applied on top of NAIC statutory Schedule D detail — security-by-security holdings reported at full depth only in the annual statement, accessible via paid Capital IQ Pro aggregation.

The opacity at each node is not an accident. It is the *downstream consequence* of the classification choices that enable the arbitrage in the first place. If funding agreements were classified as debt, they would appear in standard debt-tagged disclosure; bank-style ratios would apply to the insurer; the arbitrage would not exist in its current form. If FABS were excluded from HQLA, banks would not provide the supply of demand that keeps the chain liquid. If FHLB advances were broken out by use case, the spread-lending category would be visible. If offshore reinsurance affiliates were consolidated with their U.S. cedents for capital adequacy purposes, the capital-relief arbitrage would disappear. Each piece of opacity is structural and aligned with the regulatory regime that produces it; together they form a system in which the activity is fully legal, fully disclosed under each regime's own rules, and fully invisible as a network to any single supervisor.

---

## 4. Why the FSR shows it the way it does

The May 2026 FSR cites NAIC statutory filings via S&P Capital IQ Pro, Moody's Analytics CreditView, and Bloomberg as sources for Figures 4.9 and 4.10. The FSR's authors have access to data layers that headline GAAP XBRL does not surface. They reconstruct the four NTL components and the six illiquid-asset categories from those richer sources.

The FSR does not write an essay about disclosure opacity. It puts Figure 4.9 and Figure 4.10 in the same Pillar 4 narrative, sandwiched between text about life insurer leverage being "well into the upper quartile of its historical distribution" and language about insurers' growing investments in "risky and illiquid assets." The structure of the FSR's argument is:

1. Leverage is high (Figure 3.10)
2. Illiquid asset share is high and growing (Figure 4.10)
3. Non-traditional liabilities are large and growing fast (Figure 4.9)

The reader is expected to compose these into a single picture. The FSR does not need to spell out the arbitrage because its audience is policymakers who already understand the regulatory architecture. For a reconstruction dashboard with a broader audience, the picture has to be made explicit.

---

## 5. What the dashboard should compute

The right Pillar 4 indicator for this vulnerability is **the scale of the regulatory-arbitrage network** — how much economic activity is doing maturity transformation through the bank-MMF-FHLB-insurer chain and how much capital relief is being routed through affiliated offshore reinsurance, in a form that no single regulator measures end-to-end.

The full network has four measurable surfaces, each of which captures part of the arbitrage:

**Surface A — insurer side.** The maturity-mismatch indicator at the entity that bears the residual risk. Computed as:

- **Numerator:** an estimate of *runnable liabilities* — the four FSR Figure 4.9 components (funding agreements, FHLB advances, securities lending cash collateral, repo) — across the top-10 publicly traded life insurers.
- **Denominator:** the insurer's general account total liabilities (excluding separate account).
- **Companion measure:** *illiquid asset share* on the same general account base.

The interpretive frame is a level relative to zero, not a percentile rank against history. At zero, the insurer is doing only traditional insurance. As the runnable-liability share rises and the illiquid asset share rises in parallel, the insurer is increasingly a shadow bank — performing maturity transformation outside the regulatory regime designed for that activity.

**Surface B — bank side.** The portion of bank LCR HQLA that is in fact a credit claim on the insurer chain. Computed as a *cross-sector linkage* signal:

- Bank holdings of FABS, FABCP, and similar instruments (where disclosed in Y-9C HQLA composition or in bank Pillar 3 disclosures)
- As a fraction of the bank's stated Level 2 HQLA and as a fraction of total HQLA

This surface is significantly more opaque than the insurer-side because bank HQLA composition is not broken out by counterparty type in standardized disclosure. The dashboard's most honest treatment is to surface what *is* reportable (aggregate Level 2 HQLA across the LISCC bank panel) and document explicitly that the FABS sub-component is not directly disclosed. The size and growth of total Level 2 HQLA across the banks is a weak proxy that moves in the same direction as the unobserved FABS sub-component when the arbitrage is growing.

**Surface C — FHLB side.** The size of FHLB advances to insurer members. FHLB publishes member-level advance data quarterly and the insurance industry's share of total FHLB advances has grown materially since 2008. Computed as:

- Total FHLB advances outstanding to insurer members (from FHLB consolidated obligations reports)
- As a fraction of total FHLB advances
- As a fraction of insurer general account liabilities (cross-validates Surface A's FHLB component)

Surface C is the most cleanly observable of the four because FHLB publishes its member-balance data on a quarterly cadence with explicit category breakouts. By April 2026 published data, US insurers accounted for 26.3% of all FHLB advances (up from 21.8% at end-2024 and 10.0% ex-captives in 2016); life insurers and fraternal benefit societies alone held approximately $168 billion of FHLB advances, the vast majority for spread investing.

**Surface D — offshore reinsurance side.** The size of U.S. life insurer liabilities ceded to affiliated offshore reinsurers, and how that share is growing. Computed from NAIC Schedule S (reinsurance ceded by counterparty) data:

- Liabilities ceded to affiliated reinsurers domiciled in Bermuda, Cayman Islands, or similar jurisdictions
- As a fraction of total U.S. life insurer liabilities
- Broken out by whether the affiliated reinsurer is consolidated for U.S. capital adequacy or not
- Tracked over time to capture the growth trajectory documented in industry data

Surface D measures *capital-side* arbitrage rather than maturity-mismatch arbitrage. The two are complementary: capital relief from cessions funds the asset accumulation that the funding channels (Surfaces A-C) on the other side support. A rising Surface D means more of the U.S. life insurance balance sheet has its capital adequacy housed in a regime that U.S. financial-stability authorities do not directly supervise.

### 5.1 The composite signal

The four surfaces together form the regulatory-arbitrage network indicator. They do not collapse into a single number cleanly — the surfaces measure different points in the chain and are denominated differently — but they should be displayed and tracked together so that a user looking at Pillar 4 sees the network, not just one node.

The growth rate matters. A stable level of arbitrage indicates the activity is structurally embedded but not worsening. A rising level — which is what the FSR documents and what each of the four surfaces should show in parallel when the arbitrage is accumulating — means the vulnerability is building. A correlated rise across all four surfaces is a stronger signal than any one alone, because it indicates the activity is growing through every channel of the network rather than shifting between channels. Conversely, if Surface D rises while Surfaces A-C are stable, that signals the system is shifting capital adequacy out of U.S. supervisory view without changing the underlying maturity transformation — also a vulnerability worth flagging.

---

## 6. Implementation: what is reachable on each surface, what is not, and what to do about it

The four surfaces have very different reachability profiles. They are listed in order of decreasing data quality.

### 6.1 Surface C — FHLB advances to insurers

**Most reachable.** The Federal Home Loan Bank system publishes member-balance data quarterly through FHLB Office of Finance reports and through individual FHLB district 10-K and 10-Q filings on SEC EDGAR. Advances outstanding by member type (insurance company members vs commercial bank members vs other) are explicitly broken out. The data is free, machine-readable, and on a stable quarterly cadence. This is the cleanest of the four surfaces and probably the first to implement.

The fetcher pattern matches the existing F4 NyfedFetcher pattern (single quarterly source, multiple time series) more closely than F5 SecFetcher. A new lightweight fetcher class — call it `FhlbFetcher` — would pull the FHLB Office of Finance reports and emit one block. This is not "do not invent the bicycle" — there isn't an existing pattern for it, and the data source is structurally distinct from anything currently in the dashboard.

### 6.2 Surface D — offshore reinsurance cessions

**Second-most reachable.** Schedule S of the NAIC annual statement reports reinsurance ceded by counterparty, including the counterparty's name, jurisdiction, and affiliation status. NAIC statutory filings are available publicly through the NAIC's annual statement filing system and individual state insurance department filing portals; they are not in SEC XBRL format but are machine-readable PDFs with stable structure across insurers and years. Industry aggregations (S&P Global, AM Best, A.M. Best Statement File, FIO Annual Report) publish total reinsurance ceded to Bermuda and similar by reporting period.

The data cadence is annual rather than quarterly — Schedule S is part of the annual statement, not the quarterly statement. This is acceptable for Surface D because the cession structure is set in board-approved transactions that occur infrequently rather than quarter-to-quarter. A `NaicScheduleSFetcher` class — distinct from SecFetcher because the source is NAIC PDFs rather than SEC XBRL — would emit one annual block per LIFE_INSURERS entity, broken out by counterparty jurisdiction and affiliation. Alternative implementation: use the FIO Annual Report's published aggregate (US insurer reinsurance ceded to Bermuda, by year) as a simpler single-series block until per-insurer Schedule S parsing is built.

The surface is reachable in part because the U.S. side of the cession is fully disclosed by U.S. regulators. The opacity sits past the cession (what the offshore reinsurer actually does with the ceded reserves), not at the point of measurement (how much was ceded).

### 6.3 Surface A — insurer maturity mismatch

**Reachable from origin XBRL with significant per-insurer reconciliation work.** The data reachability is uneven across the four NTL components and across the LIFE_INSURERS panel:

| Component | Reachable from origin XBRL? | Notes |
|---|---|---|
| Repo (`SecuritiesSoldUnderAgreementsToRepurchase`) | Yes, with per-insurer tag reconciliation | PRU uses the standard tag; MET combines into a different aggregate tag; tag-discovery step required per insurer |
| Securities lending cash collateral | Yes, with per-insurer tag reconciliation | Three different tag names across PRU, LNC, VOYA; cross-insurer canonicalization required |
| Funding agreements (PAB subset) | Yes, via dimensioned-fact extraction | Each insurer uses a custom namespace axis (e.g. `met:CapitalMarketsInvestmentProductsAndStableValueGICsMember`); requires per-insurer dimension mapping |
| FHLB advances on insurer books | Partially | Some insurers tag explicitly (AIG via `AdvancesFromFederalHomeLoanBanks`); MetLife and most others fold into "Other liabilities" with no XBRL breakdown |

Where direct extraction fails on the insurer side, the **growth in "Other liabilities" that is not accounted for by disclosed components** serves as a residual lower-bound proxy. MetLife's "Other liabilities" grew $11.6B from 2024-12-31 to 2025-09-30, against disclosed-NTL growth of $2.5B and disclosed long-term debt growth of $0.2B. The ~$9B residual is, at the upper bound, the unclassified accumulation that includes (but is not limited to) FHLB advances and other obscured funding categories. The residual cannot be cleanly attributed, but its *direction* and *magnitude relative to disclosed channels* is itself an interpretable signal — and Surface C provides a cross-check, since FHLB-reported advances to insurers can be compared against the insurer-side residual to see how much of the residual is FHLB versus other.

The illiquid asset share is approximated quarterly from headline XBRL invested-asset breakdowns (mortgage loans + Schedule BA equivalent + private placement bonds where flaggable) with the Q4 reading replaced by the more detailed annual classification when 10-K filings become available. The asset-side specification can be sharpened beyond "illiquid generally" to track *insurer holdings of CLO mezzanine tranches and BDC equity specifically*, since that is where the spread-lending concentration documented in the academic literature actually shows up. SEC Form N-54A/N-54C (BDC elections) and Form NMFP (MMF holdings) provide origin sources for parts of this; NAIC Schedule D Part 1 by issuer provides the underlying detail at annual cadence. Single block, quarterly cadence, mixed-method observations within one series — the method per observation lives in the block's data, the methodology footnote lives in the block's description.

This produces a *lower bound* on the runnable-liability share rather than the FSR's full $531B figure. The lower bound is sufficient because:

1. The direction of the asset-liability mismatch is what matters for the indicator; absolute level reproduction of the FSR is not the goal.
2. The lower bound moves in the same direction as the true value when disclosed channels and undisclosed channels grow together — which is what the FSR observes.
3. Imperfect liability data combined with reasonable asset data still produces a maturity-mismatch indicator that captures the FSR's signal.
4. Cross-checking against Surface C reduces the uncertainty on the largest undisclosed component (FHLB advances).

### 6.4 Surface B — bank HQLA credit exposure

**Least reachable.** Bank LCR HQLA composition is reported in Pillar 3 disclosures and FFIEC Y-9C filings at the level of Level 1 / Level 2A / Level 2B aggregates, without breaking out which fraction is FABS, corporate bonds, GSE paper, or other credit-claim instruments. The FABS sub-component is not directly disclosed.

The dashboard's most honest treatment is to surface what *is* reportable — aggregate Level 2 HQLA across the LISCC bank panel — and document explicitly that the FABS sub-component is not directly disclosed. The size and growth of total Level 2 HQLA across the banks is a weak proxy that moves in the same direction as the unobserved FABS sub-component when the arbitrage is growing.


This block deserves the lowest quality weighting (q=0.60 or similar — vendor-grade with proxy methodology) in the v2 scoring registry, reflecting that what it measures is an *upper bound on a sub-component* rather than a direct measure. It should ship as a Pillar 4 indicator anyway, because (a) the network signal requires all four surfaces and (b) showing the gap between what *is* disclosed and what *would need to be disclosed* to see the FABS exposure directly is itself an interpretable signal.

---

## 7. What this changes about KNOWN_GAPS and the dashboard's posture

The original framing of G11 in KNOWN_GAPS was "reproduce FSR Figure 4.9's four-component NTL decomposition from origin public data." Under that framing, G11 is either a paid-aggregator-dependency gap (because the perfect reproduction requires Capital IQ Pro) or a partial-coverage block under a different name (because only some of the four components are XBRL-reachable).

The reframing in this document moves G11 from "reproduce a chart" to "measure the network arbitrage the chart is pointing at." The signal is the regulatory-arbitrage scale, computed across the four surfaces described in §5: insurer-side maturity mismatch, bank-side HQLA composition exposure, FHLB-side advances to insurer members, and offshore-reinsurance cessions of U.S. life insurer liabilities. That signal is reachable from origin public data with the imperfect data on each surface, because the *direction* and *growth rate* of the arbitrage are what the FSR is flagging and these move coherently across all four surfaces.

KNOWN_GAPS should reflect this. G11 is not deferred and not a permanent paid-dependency gap. G11 is replaced by four coordinated blocks in Pillar 4, one per surface of the arbitrage network:

- `pillar4.life_insurer_maturity_mismatch` — Surface A; runnable-liability share and illiquid-asset share at the top-10 life insurers, with documented per-insurer XBRL extraction methodology
- `pillar4.bank_hqla_credit_exposure` — Surface B; bank Level 2 HQLA composition as a weak proxy for FABS exposure within bank liquidity portfolios across the LISCC bank panel
- `pillar4.fhlb_advances_to_insurers` — Surface C; FHLB advances outstanding to insurer members, from FHLB consolidated obligations reports
- `pillar4.life_insurer_offshore_reinsurance` — Surface D; U.S. life insurer liabilities ceded to affiliated offshore reinsurers, from NAIC Schedule S or the FIO Annual Report aggregate

G12 (`pillar4.life_insurer_illiquid_asset_share`) is retained as a companion to Surface A under the same conceptual umbrella but emitted as a separate block to maintain the asset-side / liability-side decomposition the FSR uses.

The FSR's specific $531B aggregate is not the target for any of these blocks. The FSR's underlying *vulnerability signal* — the regulatory-arbitrage network — is.

---

## 8. Why this matters beyond G11

The discipline question that prompted this analysis was about narrowness of vision — looking only as far as the immediate data extraction problem rather than asking what the data is actually showing. The same discipline applies to other gaps in KNOWN_GAPS:

- **G3** (IG-vs-non-IG ICR distribution) is not just a Compustat-vs-aggregate trade-off; it is part of the FSR's broader signal about corporate debt service capacity at the margin, where a worsening tail matters more than the aggregate median.
- **G16** (non-agency securitization issuance) is not just a SIFMA-vs-Green Street trade-off; it is part of the FSR's signal about credit cycle stage, where issuance composition (CLO share, ABS quality) matters more than total volume.

The shared methodological lesson: when origin data is incomplete relative to what the FSR plots, the right question is not "how do we hack a close-enough reproduction" but "what underlying vulnerability is the FSR pointing at, and is *that* reachable from origin data?" Often the answer is yes, but only by reading the FSR's two-figure narrative composition as a single signal rather than as two separate reproduction targets.

---

## 9. Independent confirmations of the framing

The reading developed in this document is not novel. It is the consensus framing among financial-stability researchers, regulators, multilateral bodies, and the financial press that covers the sector. The document's contribution is *operationalizing the framing into a dashboard built on origin public data* — not inventing the framing. A reader can verify and extend the analysis from the following sources, organized by vantage point.

### 9.1 Academic literature (the maturity-transformation framing)

The foundational empirical work treats U.S. life insurer nontraditional liabilities as shadow-bank wholesale funding by default and identifies self-fulfilling run dynamics in the 2007–08 episode.

- **Foley-Fisher, N., Narajabad, B., & Verani, S. (2020).** "Self-Fulfilling Runs: Evidence from the US Life Insurance Industry." *Journal of Political Economy* 128(9), 3520–3569. Demonstrates that at least 40% of the $18B 2007 run on life insurer FABS by institutional investors was amplified by self-fulfilling expectations. Frames the FABS structure explicitly as bank-like activity outside the regulated banking sector.
- **Foley-Fisher, N., Narajabad, B., & Verani, S. (2019).** "Securities Lending as Wholesale Funding: Evidence from the U.S. Life Insurance Industry." NBER Working Paper. Extends the same framing to securities lending cash collateral as wholesale funding.
- **Foley-Fisher, N., Gissler, S., & Verani, S. (2019).** "Over-the-Counter Market Liquidity and Securities Lending." *Review of Economic Dynamics* 33, 272–294.
- **Foley-Fisher, N., Heinrich, N., & Verani, S. (2024).** "US Life Insurers and Systemic Risk." Chapter in *Research Handbook of Macroprudential Policy*. Synthesizes the body of work into a systemic-risk argument.

### 9.2 Federal Reserve research (the operational mechanism)

The FRB's own FEDS Notes series documents the accounting classifications that enable each channel.

- **FEDS Notes (Aug 5, 2016).** "Funding Agreement-Backed Securities in the Enhanced Financial Accounts." Foley-Fisher, Meisenzahl, Narajabad, Perozek, Verani. Establishes that "as FABS funding dried up during the financial crisis, life insurers turned to shorter duration FABS as well as the FHLB system."
- **FEDS Notes (May 21, 2019).** "Assessing the size of the risks posed by life insurers' nontraditional liabilities." Foley-Fisher, Narajabad, Verani. Notes that "FHLBs have a 'super-lien' status over other claimants that weakens the seniority of other investors" — the priority-of-claim mechanism that makes the funding chain robust in normal times and dangerous to other creditors in stress.
- **FEDS Notes (Aug 23, 2022).** "How Do U.S. Life Insurers Manage Liquidity in Times of Stress?" Foley-Fisher, Heinrich, Verani. States explicitly: *"FHLB advances do not appear as 'borrowed funds' in statutory filings because they are collateralized by funding agreements so are treated as insurance contracts rather than debt."* By end-of-sample, "insurers accounted for about 35 percent of all borrowing from the FHLB system."
- **FEDS Notes (Mar 21, 2025).** "Life Insurers' Role in the Intermediation Chain of Public and Private Credit to Risky Firms." Carlino, Foley-Fisher, Heinrich, Verani. Uses the term *"intermediation chain"* and traces it from FABS / FHLB advances / sec lending / repo through funding agreements through the insurer's general account to BSL/MM CLOs, BDCs, and PE-affiliated private credit. The framing is functionally identical to this document's §2.

### 9.3 Multilateral and U.S. regulators

The FSR is not alone in flagging this vulnerability cluster. The same picture appears at the FSB, OFR, IMF, and FIO.

- **FSB (May 6, 2026).** "Report on Vulnerabilities in Private Credit." Names "interconnectedness with insurers and private equity, cross-border interlinkages, leverage, liquidity mismatches, and concentration" as the central concerns. Estimates ~10% of life insurer portfolios in private credit (vs ~3% for non-life). Proposes "a core set of comparable metrics for authorities to track market size and growth, links with banks and insurers, leverage, liquidity features, concentration, cross-border activity" — which is in spirit the four-surface architecture this document proposes for dashboard implementation.
- **OFR Annual Report to Congress (2024, 2025).** Flags structural fragilities in short-term funding markets and rapid growth of nonbank intermediation as persistent vulnerabilities. The 2025 report covers private credit and insurer participation directly.
- **IMF Global Financial Stability Report (April 2024).** Cites private credit growth and insurer-private-equity interconnection as systemic-risk concerns. Notes that semi-liquid fund structures introduce maturity transformation outside the regulated banking sector.
- **Federal Insurance Office (Treasury), annual reports through 2025.** Engages NAIC and state regulators specifically on private-equity insurer practices, offshore reinsurance, and CLO concentration in life insurer general accounts.
- **NAIC Modernization Working Group materials, November 2025.** Establishes the accounting basis for FA-as-policyholder-reserve and FHLB-advance-as-operating-leverage classifications, and discusses tightening responses.

### 9.4 Industry data and trade publications

Independent industry aggregations confirm the size and growth trajectory.

- **S&P Global Market Intelligence (April 2026).** "Insurers' FHLB advances hit new high as spread investing flourishes." Reports U.S. insurers at 26.3% of all FHLB advances (up from 21.8% at end-2024 and 10.0% ex-captives in 2016). Life insurers alone hold $167.79B of FHLB advances; estimates $130.63B of life insurer general account deposit-type contracts are FHLB funding agreements (up from $121.68B at end-2024). Athene's US life subsidiaries rank second only to Truist Financial as the largest single FHLB borrower of any kind.
- **Bloomberg (November 2025).** "Apollo and Wall Street Private Equity Firms Bet on America's Life Insurance." Reports U.S. insurer reinsurance ceded to Bermuda grew from $205B in 2014 to $928B in 2024. Documents the Athene capital structure with 96% of $200B reinsurance offshored. Quantifies the Surface D arbitrage at industry scale.
- **Risk.net (2022) and Retirement Income Journal (ongoing).** Cover the PE-affiliated insurer model — coined the "Bermuda Triangle strategy" by RIJ in 2020 — and document the asset-side concentration: Athene at 20% portfolio in ABS, more than half in CLOs, vs industry average of 7% ABS and 2.6% CLOs (as of 2021 industry data, with the gap widening since).
- **Retirement Income Journal (June 2025).** Describes the phenomenon as "a shadow bank inside an insurer's skin" — a colorful version of this document's "fraction of the insurer that is, in effect, a bank without bank regulation." Same concept, established in trade press.
- **Harvard Business School research (2025).** Documents the closed loop between alternative asset managers and the insurers they own or affiliate with, generating fees on both sides of the balance sheet.

### 9.5 What this confirms and what it does not

The framing in this document — bank-shaped maturity transformation by entities operating outside bank regulation, intermediated by a multi-party network spanning banks, MMFs, the FHLB system, and offshore reinsurers — is established, peer-reviewed, regulator-acknowledged, and industry-disclosed. The body of evidence has accumulated since at least 2015 and is reaching policymaker consensus by 2025–2026.

What is *not* established by the literature is the specific operationalization proposed in §5–§6: the four-surface dashboard architecture, the per-insurer XBRL extraction methodology for Surface A, the FHLB Office of Finance fetcher for Surface C, the Schedule S parser for Surface D, the LISCC HQLA aggregation for Surface B. Those are this document's specific implementation proposal for a reconstruction dashboard built on origin public data. They are *consistent with* the framing the literature establishes, but the literature does not specify them; this document does. The §5–§6 design choices are accountable to the standard discipline of the dashboard (origin data, no paid aggregators, honest data-quality flagging) and should be evaluated as engineering choices, not as theoretical claims.

---

## Provenance

This document was developed in conversation between the project owner and Claude across the FSR Dashboard's Phase 11.0d gap-closure sprint, May 2026. It builds on:

- The KNOWN_GAPS.md entries for G11 (insurer non-traditional liabilities) and G12 (insurer illiquid asset share), originally classified as deferred SEC EDGAR Schedule D parsing work
- The empirical XBRL inventory for 10 LIFE_INSURERS, establishing what is and is not reachable from headline XBRL
- The MetLife Q3 2025 10-Q full-filing read, establishing the actual disclosure architecture for funding agreements (Note 5), repo and securities lending (Note 11), long-term debt (Note 14, which omits FHLB advances), and contingencies (Note 21, which omits FABN SPVs)
- The May 2026 FSR (`financialstabilityreport20260508.pdf`) Figures 4.9, 4.10, and the surrounding Pillar 4 narrative
- The NAIC Modernization Working Group materials from November 2025 establishing the accounting basis for the funding-agreement-as-policyholder-reserve classification and the FHLB-advance-as-operating-leverage classification
- An external-literature triangulation step (see §9) confirming the framing against the academic body of work led by Foley-Fisher, Narajabad, and Verani at the Federal Reserve Board; the FSB May 2026 Report on Vulnerabilities in Private Credit; OFR, IMF, and FIO publications; and industry data from S&P Global, Bloomberg, and the trade press. The document's central framing is established consensus; its specific dashboard implementation proposal is novel to this project.
