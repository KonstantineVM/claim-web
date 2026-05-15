# Project CLAIM-WEB

## Quantifying the U.S. Life Insurance Regulatory-Arbitrage Network as a Conservation Circuit

*A complete project plan: from theoretical foundations through delivered artifacts*

---

## Preamble: what this project is and what it is not

This is not a sub-component of the FSR Dashboard reconstruction. The FSR Dashboard answers *"how vulnerable is the system relative to its history?"* by scoring time series against historical bands. CLAIM-WEB answers two different questions:

1. **How large is the web of financial claims layered on top of the underlying real assets and obligations of the U.S. life insurance sector?** ("Quantify the web.")
2. **At what level of redemption demand at any single entry point does the network fail to deliver real dollars without forced asset liquidation?** ("Quantify the breaking point.")

The project's defining commitment: **money does not dissipate**. Every dollar of financial claim exists simultaneously on two balance sheets (as someone's asset and someone's liability), and at every node total inflows equal total outflows (the balance sheet identity). These conservation laws are not soft constraints to be approximated; they are the mathematical structure that makes the unobserved arcs *computable* from the observed arcs and the sectoral boundary conditions.

The project's audacity: this conservation-circuit framing is mature in academic systemic-risk literature (Eisenberg-Noe 2001, Cifuentes-Ferrucci-Shin 2005, Battiston et al. 2012, Anand-Craig-von Peter 2015, Cont-Schaanning 2017, Acemoglu-Ozdaglar-Tahbaz-Salehi 2015). It has been applied to interbank networks repeatedly. It has *not* been applied to the bank–money market fund–FHLB–life insurer–PE asset manager–offshore reinsurer network in the configuration the May 2026 FSR Pillar 4 describes, with proper accounting for the asymmetric accounting classifications (insurance reserve vs debt vs HQLA vs operating leverage) that enable the arbitrage in the first place. The methodological tools exist; the specific application is novel.

The project's discipline: every estimated quantity carries an explicit uncertainty band, every model assumption is documented in machine-readable form, every conclusion is validated against the three known historical episodes (2007 XFABS run, 2008 AIG securities lending collapse, March 2020 prime MMF / repo-intermediation stress). A model that cannot retrodict those three episodes is not credible for prospective use; the validation step is not optional.

---

## Part I — Foundations

### 1. The conservation-circuit framing, formal statement

Let $V$ be the set of nodes in the financial network. Each node $v \in V$ is a legal entity or a precisely-defined aggregation of legal entities (defined in Part III). Let $K$ be the set of claim types ("instruments") — funding agreements, FABNs, FHLB advances, repo positions, securities-lending cash collateral, reinsurance treaties, CLO mezzanine tranches, money market fund shares, etc.

For any pair of nodes $(i, j) \in V \times V$ and any instrument $k \in K$, let $x_{ij}^k(t) \geq 0$ be the dollar volume of instrument $k$ that is held by $i$ as an asset and issued by $j$ as a liability at time $t$. This is the **arc weight** on the directed edge from issuer $j$ to holder $i$ for instrument $k$.

The network state at time $t$ is the tensor $X(t) = \{x_{ij}^k(t)\}_{i,j \in V, k \in K}$.

#### 1.1 Conservation laws (the Kirchhoff structure)

**Law 1 — Balance sheet identity (node-level KCL).** For every node $i$ and every period $t$:
$$\sum_{j \in V} \sum_{k \in K} x_{ij}^k(t) + N_i(t) = \sum_{j \in V} \sum_{k \in K} x_{ji}^k(t) + E_i(t)$$
where $N_i(t)$ is non-financial assets at node $i$ and $E_i(t)$ is equity (residual). Total assets equal total liabilities plus equity. Always. At every node. In every period. This is the fundamental accounting identity.

**Law 2 — Double-entry consistency (instrument-level conservation).** For every instrument $k$ and every period $t$:
$$\sum_{i,j \in V} x_{ij}^k(t) = \text{(sum of all holdings of } k \text{ by parties in } V)$$
and this equals the sum of all issuances of $k$ by parties in $V$ provided the network boundary captures all issuers and holders. When the boundary is incomplete (some parties are outside $V$, in the rest-of-world or in the unmodeled tail of small institutions), the residual is a boundary term that must itself be accounted for.

**Law 3 — Sectoral aggregate constraint (Z.1 boundary conditions).** For every sector $s$ (life insurers, banks, MMFs, etc.) and every instrument $k$, the Federal Reserve's Z.1 release publishes the total holdings of $k$ by sector $s$:
$$\sum_{i \in s} \sum_{j \in V} x_{ij}^k(t) = Z_{s,k}^{\text{asset}}(t) \quad ; \quad \sum_{j \in s} \sum_{i \in V} x_{ij}^k(t) = Z_{s,k}^{\text{liab}}(t)$$
These are published quarterly with documented methodology and act as **upper-level Kirchhoff equations** for the aggregated nodes.

**Law 4 — Flow-of-funds identity (transactions vs positions).** Change in arc weight between adjacent periods equals net transactions plus revaluation:
$$x_{ij}^k(t+1) - x_{ij}^k(t) = F_{ij}^k(t \to t+1) + R_{ij}^k(t \to t+1)$$
where $F$ is net new transactions (issuance minus redemption) and $R$ is mark-to-market revaluation. The Z.1 publishes both stock (L.tables) and flow (F.tables) consistently, providing two independent constraints per period.

#### 1.2 Why the laws constitute a solvable system even with partial direct observation

The unknowns are the entries of $X(t)$ — at full granularity, $|V| \times |V| \times |K|$ unknowns per period. The observed quantities are: a subset of $X(t)$ directly disclosed (via SEC XBRL, FHLB Office of Finance, NAIC Schedule S, SEC Form NMFP, SEC Form 13F, SEC Form ADV); the marginals of $X(t)$ from each entity's published balance sheet totals (per-entity, every quarter, from 10-Q/10-K); the sectoral totals $Z_{s,k}(t)$ from Z.1.

This is structurally identical to the problem solved by Anand-Craig-von Peter (2015) in *Filling in the Blanks: Network Structure and Interbank Contagion* (Quantitative Finance 15(4): 625-636) and by the broader literature on bilateral-exposure estimation surveyed by Upper (2011). The standard approach is:

1. **Hard constraints** — apply Laws 1, 2, 3, 4 as linear equality constraints on the unknown $x_{ij}^k$.
2. **Estimation principle for residual freedom** — when the constraints leave a feasible manifold rather than a unique point, choose among feasible solutions by a principle (maximum entropy in Upper 2004; minimum density in Anand-Craig-von Peter 2015; we will use *both* and report the spread between them as a structural-uncertainty band, following Anand et al.'s explicit recommendation that the two solutions bracket the true network).
3. **Soft constraints from prior knowledge** — entity-type compatibility (an SPV holds at most one funding agreement and issues at most one class of FABN; a money market fund's holdings must satisfy Rule 2a-7 maturity and credit limits; an FHLB's advances are collateralized by member-pledged eligible collateral). These appear as additional regularizers in the estimation objective.

The methodological core, in equation form, is the constrained-optimization problem:
$$\hat{X}(t) = \arg \min_{X} \; \mathcal{L}(X) \quad \text{subject to Laws 1–4 and direct observations}$$
where $\mathcal{L}$ is the chosen estimation principle (maximum entropy: $-\sum_{ij,k} x_{ij}^k \log x_{ij}^k$; minimum density: a sparsity-inducing penalty consistent with empirically observed network structure).

This problem is convex in the maximum-entropy formulation and tractable in the minimum-density formulation via the relaxation method of Anand, Craig, and von Peter. Both have published reference implementations (the R package `NetworkRiskMeasures` ships both).

#### 1.3 The breaking point, formally

The clearing-vector framework of Eisenberg and Noe (2001) provides the canonical formalization. Given the solved network $\hat{X}(t)$ and a vector $c(t)$ of cash and cash-equivalent holdings at each node (real-dollar capacity, defined in Part II), the clearing payment vector $p^*$ is the largest fixed point of:
$$p_i^* = \min\left( \bar{p}_i, \; c_i + \sum_j \pi_{ji} p_j^* \right)$$
where $\bar{p}_i$ is node $i$'s total liabilities (the row sum of $\hat{X}$ on the liability side) and $\pi_{ji}$ is the relative claim of $i$ on $j$. This is solved by Eisenberg-Noe's fictitious-default algorithm in polynomial time.

For a redemption shock vector $\Delta r$ applied at chosen entry nodes (typically MMF holders, FABN holders, FHLB-advance demand), the **breaking point** $\theta^*$ is the smallest scalar multiple of $\Delta r$ such that the resulting clearing payment vector forces at least one node into default:
$$\theta^* = \inf \{ \theta > 0 : \exists i, \, p_i^*(\theta \Delta r) < \bar{p}_i \}$$

With fire-sale dynamics (Cifuentes-Ferrucci-Shin 2005, Cont-Schaanning 2017), this is augmented: when a node is forced to liquidate illiquid assets to meet redemptions, the liquidation moves prices, marking down everyone's portfolio, which in turn forces more liquidations. Cont-Schaanning's "indirect contagion" framework computes the fire-sale-augmented clearing vector under a parameterized price-impact function calibrated from empirical asset liquidity (Pavlova-Petrasek for corporate bonds, Greenwood-Landier-Thesmar for the general framework).

The breaking-point output of the project is not a single number; it is a **per-entry-point threshold function** mapping (shock origin, shock instrument, shock magnitude) → (cascade depth, cascade reach, total real-dollar shortfall, identity of defaulting nodes).

### 2. Literature foundation

The intellectual debts of this project, grouped by what each contributes:

#### 2.1 The maturity-transformation problem (what kind of system this is)

Diamond and Dybvig (1983), "Bank Runs, Deposit Insurance, and Liquidity," *Journal of Political Economy* 91(3): 401–419. The foundational analysis of liquidity insurance via demand deposits. Establishes that a bank performing maturity transformation — long illiquid asset, short liquid liability — has multiple equilibria, one of which is a self-fulfilling run. Diamond and Bernanke received the 2022 Nobel Memorial Prize in part for this work. CLAIM-WEB treats the network as a generalized Diamond-Dybvig structure in which the maturity transformation is distributed across many entities rather than concentrated in one bank.

Goldstein and Pauzner (2005), "Demand-Deposit Contracts and the Probability of Bank Runs," *Journal of Finance* 60(3): 1293–1327. Extends Diamond-Dybvig to global-games equilibrium selection, yielding unique-equilibrium predictions of run probability as a function of fundamentals. Provides the framework for parameterizing the *self-fulfilling component* of a run, separately from fundamental-based default.

#### 2.2 Network-level clearing and contagion

Eisenberg and Noe (2001), "Systemic Risk in Financial Systems," *Management Science* 47(2): 236–249. The seminal clearing-payment-vector framework. Establishes existence, uniqueness under mild conditions, and a polynomial-time algorithm. Every subsequent paper on financial network contagion builds on this.

Cifuentes, Ferrucci, and Shin (2005), "Liquidity Risk and Contagion," *Journal of the European Economic Association* 3(2/3): 556–566. Adds price-mediated contagion (fire sales) to the Eisenberg-Noe framework. Critical for our setting because the life insurer general account holds illiquid CLO mezzanine tranches and CRE loans whose fire-sale price impact is the dominant transmission channel.

Rogers and Veraart (2013), "Failure and Rescue in an Interbank Network," *Management Science* 59(4): 882–898. Introduces dead-weight losses from default — when a node defaults, its creditors recover less than face value due to bankruptcy costs. Important for the recovery-rate parameter in the cascade analysis.

Acemoglu, Ozdaglar, and Tahbaz-Salehi (2015), "Systemic Risk and Stability in Financial Networks," *American Economic Review* 105(2): 564–608. Generalizes the clearing-vector framework with multi-seniority liabilities and partial liquidation. Establishes the *phase transition*: for small shocks, dense networks are more stable than sparse ones; for large shocks, the opposite is true. Tells us our breaking-point analysis must distinguish small-shock and large-shock regimes.

Battiston, Puliga, Kaushik, Tasca, and Caldarelli (2012), "DebtRank: Too Central to Fail? Financial Networks, the FED and Systemic Risk," *Scientific Reports* 2: 541. Introduces DebtRank, a feedback-centrality measure of systemic importance that captures distress propagation even without default. Used to identify nodes whose stress propagates most widely, not only those that default outright.

Feinstein, Pang, Rudloff, Schaanning, Sturm, and Wildman (2018), "Sensitivity of the Eisenberg-Noe Clearing Vector to Individual Interbank Liabilities," *SIAM Journal on Financial Mathematics* 9(4): 1286–1325. Provides the formal sensitivity analysis we need to report uncertainty bands on the clearing-vector output.

Banerjee and Feinstein (2019), "Impact of Contingent Payments on Systemic Risk in Financial Networks," *Mathematics and Financial Economics* 13: 617–636. Extends Eisenberg-Noe to contingent payments (CDS, certain reinsurance contracts). Necessary for properly handling the offshore reinsurance arc in our network, since reinsurance payments are contingent on the cedent's underlying liability development.

#### 2.3 Network estimation from partial observation

Upper (2011), "Simulation methods to assess the danger of contagion in interbank markets," *Journal of Financial Stability* 7(3): 111–125. Surveys the maximum-entropy approach to estimating unobserved interbank exposures from marginal sums. Establishes the field.

Anand, Craig, and von Peter (2015), "Filling in the Blanks: Network Structure and Interbank Contagion," *Quantitative Finance* 15(4): 625–636. Proposes the minimum-density alternative to maximum entropy and shows that the two methods bracket the true network's stress-test outcomes — maximum entropy underestimates contagion, minimum density overestimates it. **Both will be used in CLAIM-WEB and the resulting bracket reported as a structural-uncertainty band.**

Mistrulli (2011), "Assessing financial contagion in the interbank market: Maximum entropy versus observed interbank lending patterns," *Journal of Banking & Finance* 35(5): 1114–1127. Empirical comparison using Bank of Italy supervisory data showing the maximum-entropy method substantially underestimates contagion losses when the true network is concentrated.

Gandy and Veraart (2017), "A Bayesian Methodology for Systemic Risk Assessment in Financial Networks," *Management Science* 63(12): 4428–4446. Provides the Bayesian framework for incorporating prior beliefs about network structure (e.g., core-periphery topology, observed bilateral relationships) into the estimation.

#### 2.4 Fire sales and price-mediated contagion

Greenwood, Landier, and Thesmar (2015), "Vulnerable Banks," *Journal of Financial Economics* 115(3): 471–485. Establishes the canonical model of leverage-targeting-induced fire sales. The price-impact parameter from this paper calibrates the inverse demand function in our cascade simulator.

Duarte and Eisenbach (2021), "Fire-Sale Spillovers and Systemic Risk," *Journal of Finance* 76(3): 1251–1294. Provides the empirically calibrated fire-sale-spillover framework for the U.S. banking system, with asset-liquidity parameters by asset class. The asset-class-specific price-impact parameters are directly usable for our calibration.

Cont and Schaanning (2017), "Fire Sales, Indirect Contagion and Systemic Stress Testing," SSRN 2955646. The state-of-the-art framework for combining direct (counterparty) and indirect (price-mediated) contagion. Provides the algorithmic basis for the cascade simulator.

Coen, Lepore, and Schaanning (2019), "Taking Regulation Seriously: Fire Sales under Solvency and Liquidity Constraints," Bank of England Staff Working Paper 793. Extends fire-sale models to multi-constraint regulatory regimes (capital ratio + LCR + leverage). Critical for our setting because the regulatory regimes that bind each node type differ — banks have LCR/NSFR/CET1; insurers have RBC; FHLB has FHFA capital rules; offshore reinsurers have BMA or CIMA rules. The cascade simulator must respect the binding constraint at each node.

#### 2.5 Insurance-specific contagion

Foley-Fisher, Narajabad, and Verani (2020), "Self-Fulfilling Runs: Evidence from the US Life Insurance Industry," *Journal of Political Economy* 128(9): 3520–3569. The empirical demonstration that at least 40% of the 2007 $18B XFABS run was self-fulfilling. The historical case study against which CLAIM-WEB's retrodiction validation will be performed.

Foley-Fisher, Gissler, and Verani (2019), "Over-the-Counter Market Liquidity and Securities Lending," *Review of Economic Dynamics* 33: 272–294. Analytical framework for sec-lending as wholesale funding. The framework for parameterizing the sec-lending arc's run dynamics.

Foley-Fisher, Heinrich, and Verani (2024), "US Life Insurers and Systemic Risk," in *Research Handbook of Macroprudential Policy*. Synthesizes the body of work into a systemic-risk argument. Provides the conceptual framing that CLAIM-WEB operationalizes.

Carlino, Foley-Fisher, Heinrich, and Verani (2025), "Life Insurers' Role in the Intermediation Chain of Public and Private Credit to Risky Firms," FEDS Notes (March 21, 2025). Uses the term "intermediation chain" and traces it from FABS / FHLB / sec lending / repo through funding agreements through the insurer's general account to BSL/MM CLOs, BDCs, and PE-affiliated private credit. Defines the asset-side specification for our network.

Koijen and Yogo (2022), "The Fragility of Market Risk Insurance," *Journal of Finance* 77(2): 815–862. Analytical framework for variable annuity guarantees as contingent liabilities. Necessary if we extend the project to variable-annuity insurers (e.g., MetLife, Prudential VA blocks).

#### 2.6 Money market funds and the FABS demand side

Schmidt, Timmermann, and Wermers (2016), "Runs on Money Market Mutual Funds," *American Economic Review* 106(9): 2625–2657. Empirical framework for MMF run dynamics and the relationship between investor sophistication and run propensity.

Cipriani, La Spada, and Mulder (2023), "Investors' Appetite for Money-like Assets: The MMF Industry After the 2014 Regulatory Reform," *Journal of Financial Economics* 148(2): 196–217. The 2014 reform (floating NAV for institutional prime MMFs) changed the run dynamics; the FABN-holding behavior of prime MMFs post-reform is the relevant empirical baseline for CLAIM-WEB.

#### 2.7 Sector-of-sector and PE-affiliated insurers

Kirti and Sarin (2024), "What Private Equity Does Differently: Evidence from Life Insurance," *Review of Financial Studies* (forthcoming). Provides the empirical baseline for PE-affiliated insurers' asset allocation differences. Athene-Apollo, KKR-Global Atlantic, Blackstone-F&G, Brookfield-American Equity differ from traditional insurers in measurable, documented ways.

Cortes, Diez de los Rios, and Verani (2025) and related FEDS work on the PE-CLO-insurer integration loop. Documents the closed-loop structure between PE asset managers and their affiliated insurers, including affiliated CLO management fees, intra-cluster asset sourcing, and offshore reinsurance.

#### 2.8 Private credit, BDCs, and CLO contagion

Recent work treats private credit as the principal nonbank channel for systemic risk in the 2020s, the way subprime mortgages were the principal channel in the 2000s. Three lines of work directly inform CLAIM-WEB's terminal-exposure side (T3 nodes plus the CLO arc class A7).

Moody's Analytics (June 2025), "Private Credit & Systemic Risk." Documents the rapid growth of bank–BDC, bank–insurer, and BDC–insurer interconnections post-2020, using Granger-causality and PCA-based network measures on monthly market data for 60 large U.S. financial institutions over 2004–2024. Establishes that BDC co-movement with system-wide risk factors increased markedly since COVID-19 and remained elevated post-pandemic. The paper's monthly Granger-network reconstruction methodology is a useful market-based cross-check on our balance-sheet-based reconstruction.

Corominas et al. (2026), commentary in industry press warning that private credit losses eroding insurer solvency "would not resemble the bank-run dynamics of 2008, but would instead manifest as a slow, grinding erosion of retirement security — harder to detect in real time, and significantly more difficult to reverse." Frames the asymmetric run dynamic — life insurance liabilities are not demand-redeemable in the bank-deposit sense but are subject to surrenders, lapse, and forced lapsation under adverse experience — which informs our runnability classification (§6).

FSB (May 2026), "Report on Vulnerabilities Associated with Private Credit." Estimates private credit accounts for ~10% of life insurer portfolios (vs ~3% non-life); proposes a core set of metrics for monitoring NBFI–insurer–bank interconnectedness. The metric architecture proposed by the FSB is roughly congruent with CLAIM-WEB's four-surface architecture; the project's published outputs can be mapped to the FSB's metrics for direct policy uptake.

Aramonte and Avalos (2021), "The rise of private markets," BIS Quarterly Review (December). Provides the empirical baseline for private credit growth and the macro environment driving it. The paper's price-impact and liquidity-mismatch parameters inform the fire-sale calibration for the CLO/BDC asset class.

Chernenko, Erel, and Prilmeier (2022), "Why Do Firms Borrow Directly from Nonbanks?," *Review of Financial Studies* 35(11): 4902–4947. Documents the borrower-side characteristics of direct lending and provides the empirical basis for modeling the T3 terminal-exposure side (mid-market firms whose creditworthiness deteriorations propagate up the chain).

#### 2.9 Variable annuity contingent claims (Koijen-Yogo and follow-ons)

Several major U.S. life insurers (MetLife historically, Brighthouse, Equitable, Prudential, Lincoln, Voya) have very large variable annuity blocks with guaranteed minimum benefits (GMxB riders — GMDB, GMIB, GMWB, GMAB). These are *contingent liabilities* whose value depends on equity-market levels and policyholder behavior (lapse, withdrawal, annuitization). They are a major channel by which equity-market shocks translate to insurer solvency stress.

Koijen and Yogo (2022), "The Fragility of Market Risk Insurance," *Journal of Finance* 77(2): 815–862. The analytical framework for variable annuity guarantees as systemic risk; provides the methodology for marking GMxB liabilities to a market-consistent value. Critical for CLAIM-WEB because the VA blocks at MET (legacy), BHF, EQH, PRU, VOYA, LNC are large and their contingent-claim valuation drives a substantial fraction of those insurers' solvency.

Koijen and Yogo (2015), "The Cost of Financial Frictions for Life Insurers," *American Economic Review* 105(1): 445–475. Documents the shadow cost of capital for life insurers and the resulting incentives to engage in regulatory arbitrage (offshore reinsurance, captive insurance, etc.). Provides the economic-theory underpinning for Channel E being rational from each party's local incentive structure.

Sen (2023), "Regulatory Limits to Risk Management," *Review of Financial Studies* 36(6): 2535–2582. Documents how variable annuity hedging programs broke down during March 2020 and contributed to systemic risk transmission. Provides parameters for hedging-program failure modes that CLAIM-WEB's cascade simulator should respect.

These contingent-claim arcs are handled in the cascade simulator using the Banerjee-Feinstein (2019) extension cited in §2.2.

#### 2.10 Agent-based modeling for financial vulnerability

The clearing-vector approach (Eisenberg-Noe and extensions) is one of two major methodological traditions in network systemic risk analysis. The other is agent-based modeling (ABM), where each node is an autonomous agent with decision rules and the system's behavior emerges from agent interactions. ABM is more flexible (handles heterogeneous behavior, non-equilibrium dynamics, intra-period sequencing) but less tractable analytically.

Bookstaber, Paddrik, and Tivnan (2018), "An Agent-Based Model for Financial Vulnerability," *Journal of Economic Interaction and Coordination* 13(2): 433–466. The OFR's agent-based stress-testing framework. Models the financial system as a network of agents (banks, hedge funds, MMFs, dealers) with funding and collateral flows; reveals propagation pathways for fire sales and runs that equilibrium models miss. Provides the architectural template for CLAIM-WEB's parallel ABM layer (§38 below).

Bookstaber and Paddrik (2015), "An Agent-Based Model for Crisis Liquidity Dynamics," OFR Working Paper 2015-18. Extends the framework to crisis-period liquidity provision, with explicit handling of the dealer-bank intermediation pullback documented in 2008 and 2020. Directly relevant to our March 2020 retrodiction.

Bookstaber (2017), "Agent-Based Models for Financial Crises," *Annual Review of Financial Economics* 9: 85–100. The methodological survey; establishes when ABM adds value over equilibrium models.

Liu, Paddrik, Yang, and Zhang (2020), "Interbank contagion: An agent-based model approach to endogenously formed networks," *Journal of Banking & Finance* 112. Combines ABM with endogenous network formation; relevant for modeling how the network structure itself evolves under stress (e.g., dealer banks reducing repo intermediation triggers structural network change, not just arc-weight change).

Farmer and Geanakoplos (2009), "The Virtues and Vices of Equilibrium and the Future of Financial Economics," *Complexity* 14(3): 11–38. The foundational methodological argument for ABM in financial economics; CLAIM-WEB adopts the ABM as a complement, not a substitute, for the analytical clearing-vector model.

Caccioli, Shrestha, Moore, and Farmer (2014), "Stability analysis of financial contagion due to overlapping portfolios," *Journal of Banking & Finance* 46: 233–245. The seminal treatment of overlapping-portfolio contagion. Mathematical companion to Cont-Schaanning 2017.

#### 2.11 Global games and run-equilibrium selection

The Eisenberg-Noe framework computes the clearing payment vector *given* a default. It does not endogenously generate the run that triggers the default. For that, the global-games literature provides the equilibrium-selection mechanism.

Morris and Shin (1998), "Unique Equilibrium in a Model of Self-Fulfilling Currency Attacks," *American Economic Review* 88(3): 587–597. The foundational global-games selection of a unique equilibrium under noisy signals about fundamentals.

Goldstein and Pauzner (2005), "Demand-Deposit Contracts and the Probability of Bank Runs," *Journal of Finance* 60(3): 1293–1327. Applies global games to bank runs; produces a unique-equilibrium probability of run as a function of fundamentals. Provides the formula CLAIM-WEB uses to compute *probability* (not just capacity) of each entry-node shock occurring.

Rochet and Vives (2004), "Coordination Failures and the Lender of Last Resort," *Journal of the European Economic Association* 2(6): 1116–1147. Applies global games to interbank runs and lender-of-last-resort policy; provides the framework for evaluating how Federal Reserve / FHLB liquidity backstops change the breaking-point thresholds.

#### 2.12 Regulatory frameworks and accounting classifications

The arbitrage that CLAIM-WEB measures is enabled by specific regulatory and accounting classifications. The literature on those classifications is itself a research area.

BIS LCR framework (Basel Committee, 2013 with subsequent amendments). The Liquidity Coverage Ratio rule that makes FABS holdings count as HQLA on bank balance sheets. Provides the operational definition of Level 1 / Level 2A / Level 2B HQLA used in our real-dollar-capacity tiers (§5).

NAIC Annual Statement Instructions and Statements of Statutory Accounting Principles (SSAPs). SSAP No. 52 (Deposit-Type Contracts), SSAP No. 86 (Derivatives), and SSAP No. 61R (Life, Deposit-Type and Accident and Health Reinsurance) define the statutory classification of funding agreements, FHLB advances, and reinsurance treaties on the U.S. insurer side.

Bermuda Monetary Authority, "Insurance (Group Supervision) Rules" and "Economic Balance Sheet Framework." Defines the capital regime for Bermuda reinsurers; in combination with NAIC SSAP No. 61R, fully specifies the capital-relief arithmetic of Channel E.

Federal Housing Finance Agency, "FHLBank System Regulations" (12 CFR Parts 1201–1280). Defines the FHLB advance collateral framework and super-lien priority; combined with the bankruptcy code's treatment of FHLB liens, establishes the priority structure used in our cascade simulator.

Financial Stability Board (May 2025), "Global Monitoring Report on Non-Bank Financial Intermediation 2024." Provides the global context and methodology for cross-jurisdictional NBFI monitoring; CLAIM-WEB's outputs are designed to map to the FSB's monitoring categories for direct uptake.

#### 2.13 Flow-of-funds and sectoral accounting

Federal Reserve Z.1, "Financial Accounts of the United States." Quarterly release, published since 1952. The U.S. flow-of-funds accounts. Provides the sectoral boundary conditions (Law 3 above).

Shrestha, Mink, and Fassler (2012), "An Integrated Framework for Financial Positions and Flows on a From-Whom-to-Whom Basis: Concepts, Status, and Prospects," IMF Working Paper WP/12/57. The methodological foundation for from-whom-to-whom matrix construction.

Zhang and Zhao (2022), "Measuring global flow of funds: who-to-whom matrix and financial network," *Japanese Journal of Statistics and Data Science* 5: 441–471. The most recent extension of from-whom-to-whom methodology to global stocks-and-flows analysis with cross-border arcs.

#### 2.14 Computational infrastructure

The `NetworkRiskMeasures` R package (Souza et al., CRAN) implements both maximum-entropy and minimum-density estimators with the Anand-Craig-von Peter convention. Python equivalents exist (`networkx` for graph operations; custom optimization in `cvxpy` or `scipy.optimize` for the entropy and density estimators).

The `pyomo` and `scipy.optimize` packages provide the convex optimization solvers needed for the entropy-maximization problem. For the Eisenberg-Noe fictitious-default algorithm, custom implementation is straightforward (the algorithm fits in roughly 100 lines of Python).

The Cont-Schaanning fire-sale algorithm requires custom implementation but the reference paper provides full pseudocode. Total implementation effort: ~2000 lines of Python for the core algorithms.

---

## Part II — Definitions

### 3. Node taxonomy

The project's node classification, with strict definitions to prevent classification ambiguity:

#### 3.1 Money-providing nodes (sources of real dollars into the system)

**M1: Retail savers.** Households purchasing annuities directly, or holding MMF shares directly. Disclosed in aggregate in Z.1 L.117 (life insurance reserves of households) and L.121 (MMF shares held by households).

**M2: Institutional MMF investors.** Pension funds, corporate treasuries, sovereign wealth funds holding MMF shares. Z.1 L.121 row for each holding sector; SEC Form NMFP for the MMF side.

**M3: Bank treasuries deploying reserves into HQLA.** The LISCC bank panel (Bank of America, Citigroup, Goldman Sachs, JPMorgan, Morgan Stanley, State Street, BNY Mellon, Wells Fargo, Northern Trust, U.S. Bancorp, PNC, Truist, Capital One). FFIEC Y-9C HQLA composition (Schedule HC-R for capital, supplemental schedules for LCR-specific data).

**M4: Capital markets investors in FHLB consolidated obligations.** Foreign central banks, U.S. mutual funds, individual investors. Holdings disclosed in FHLB Combined Financial Report and Federal Reserve Z.1 L.211 (GSE securities).

**M5: Foreign investors in U.S. credit markets.** Z.1 L.107 rest-of-world sector. Includes foreign holdings of FABS, U.S. life insurer debt, etc.

#### 3.2 Intermediating nodes (passing claims through, taking fee/spread)

**I1: Money market funds.** Individual prime MMFs (10–15 largest by AUM, e.g., JPMorgan Prime Money Market, Fidelity Investments Money Market Fund, BlackRock Liquidity Funds) plus an aggregated "Other MMFs" node. SEC Form NMFP (monthly) provides full portfolio holdings; SEC Form N-CSR (semi-annual) provides additional detail.

**I2: FABS special purpose vehicles (SPVs).** Bankruptcy-remote conduits issuing FABNs. Each insurer's program is a distinct SPV; e.g., Metropolitan Life Global Funding I, Prudential Funding LLC, etc. Rating agency reports (Moody's, S&P) provide the SPV roster and outstanding amounts; the Federal Reserve's Enhanced Financial Accounts FABS project (Foley-Fisher, Meisenzahl, Narajabad, Perozek, Verani 2016) provides daily issuance and outstanding data.

**I3: Federal Home Loan Banks.** 11 regional FHLBs (Atlanta, Boston, Chicago, Cincinnati, Dallas, Des Moines, Indianapolis, New York, Pittsburgh, San Francisco, Topeka). Each is its own legal entity, SEC registrant, and quarterly 10-Q filer. The Office of Finance issues the consolidated obligations. Combined Financial Report quarterly.

**I4: Dealer banks acting in repo and securities-lending intermediation.** Same LISCC panel as M3 plus a few additional broker-dealer subsidiaries. The repo book is in the dealer's broker-dealer subsidiary (e.g., JPMS, Goldman Sachs & Co. LLC). SEC Form X-17A-5 (Financial and Operational Combined Uniform Single Report, FOCUS) by broker-dealer subsidiary; FRB OFR collection on non-centrally cleared bilateral repo (beginning December 2024).

**I5: Custodian banks running securities-lending programs.** BNY Mellon, State Street, Northern Trust primarily. Form 10-K and Form 10-Q disclosures of off-balance-sheet securities-lending program assets.

**I6: Alternative asset managers with affiliated insurance operations.** Apollo Global Management, Blackstone, KKR, Brookfield, Carlyle, BlackRock, Ares, plus the long tail. SEC Form ADV provides the affiliation registry; 10-K filings disclose insurance subsidiaries; Form 13F discloses public security holdings of AAM-managed funds.

**I7: CLO managers.** Sometimes the same entity as I6 (Apollo manages CLOs and owns Athene), sometimes separate (CIFC, Onex Credit). Issuer-level data from Leveraged Commentary & Data (LCD, paid; for our origin-data discipline, we use SEC Form 10-D filings by CLO issuers and Form X-17A-5 by underwriting banks as a free substitute) and Moody's Analytics CLO collateral data.

**I8: BDC vehicles.** Public and private business development companies that lend to mid-market borrowers and may be held by insurers. SEC Form N-54A/C (BDC elections) and Form 10-K/10-Q filings disclose ownership and asset composition.

**I9: Foreign banks holding FABS or other U.S. life insurer instruments.** Reachable for the largest via Treasury TIC data and from the corresponding parties' home-country regulatory disclosures.

#### 3.3 Terminal-economic-exposure nodes (where the maturity transformation actually sits)

**T1: U.S. life insurer legal entities.** The top-10 publicly traded LIFE_INSURERS (MET, PRU, AIG, LNC, PFG, GL, VOYA, RGA, BHF, EQH) at *legal-entity* granularity (each NAIC-filing subsidiary), plus the PE-affiliated insurers (Athene, Global Atlantic, F&G, American Equity, Resolution Life, etc.), plus an aggregated "Other U.S. life insurers" node capturing the long tail (~700 NAIC filers, of which only a few hundred do meaningful NTL activity).

**T2: Offshore reinsurance affiliates.** Bermuda-domiciled and Cayman-domiciled affiliates of the T1 entities, plus standalone offshore reinsurers (RenaissanceRe Life, etc., where they participate in U.S. life cessions). NAIC Schedule S provides the U.S.-side disclosure of cessions by counterparty; the offshore entity's own filings (if publicly traded) provide the other-side detail; for private offshore affiliates, the parent's 10-K consolidation note provides the implied detail.

**T3: Risky-firm borrowers and CRE properties.** Aggregated nodes representing the ultimate users of credit. BSL borrowers in the LSTA loan-index (or LCD database); CRE properties pledged in CMBS; mid-market borrowers in BDC portfolios. These are not modeled at entity granularity (~thousands of distinct borrowers); they are aggregated by industry sector and credit-quality tier, with aggregate constraints from BLS/Census/CRE-specific data sources.

#### 3.4 Regulatory nodes (overlay graph G2; see Part III)

**R1: SEC.** Supervises MMFs (Rule 2a-7), public companies (10-K/Q reporting), broker-dealers (FOCUS), investment advisers (Form ADV), BDCs (Form N-54A/C).
**R2: Federal Reserve Board of Governors (BHC supervision).** Supervises LISCC banks via CCAR/DFAST.
**R3: OCC.** National banks (often the operating subsidiary of the BHC).
**R4: FDIC.** State non-member banks and insured depository institutions.
**R5: FHFA.** FHLB system and Fannie/Freddie.
**R6: State insurance regulators (delegated through NAIC).** U.S. life insurer subsidiaries.
**R7: Bermuda Monetary Authority (BMA).** Bermuda reinsurers.
**R8: Cayman Islands Monetary Authority (CIMA).** Cayman reinsurers.
**R9: FIO (Treasury).** Federal coordinator with no direct supervisory authority.
**R10: OFR (Treasury).** Data and research; no supervisory authority.
**R11: FSOC.** Cross-cutting designation authority; rarely used.

### 4. Arc taxonomy

The arcs are typed by instrument class. The taxonomy is deliberately granular because different instruments have different runnability characteristics (Part V's cascade-rules database).

**A1: Funding agreements (cash-funded, on-shore).** Insurer issues, SPV or FHLB or institutional buyer holds. Quarterly redeemable in the case of FABS-backed; non-redeemable but puttable in stress for some FHLB structures; non-redeemable for general account institutional placements.

**A2: FABNs (Funding Agreement-Backed Notes).** SPV issues, MMF / bank treasury / institutional investor holds. Maturities ranging from overnight (FABCP) to 5+ years (medium-term FABN). XFABS (extendible FABN) have a put option at every reset date — the 2007 run was on XFABS.

**A3: FHLB advances.** FHLB issues, insurer (or bank, or other member) holds. Callable in some structures, term in others; collateralized by member-pledged assets.

**A4: Repo (securities sold under agreements to repurchase).** Dealer bank or other counterparty holds, insurer (or other party) issues. Overnight to short-term maturity; rolled or terminated at maturity.

**A5: Securities-lending cash collateral.** Custodian or dealer holds, insurer's reinvested cash collateral is the "liability" arc. Open-ended; recallable at the lender's option in most master agreements.

**A6: Reinsurance treaties (offshore-cession).** U.S. cedent transfers liability and underlying reserves to offshore reinsurer. Multi-year contractual; recapturable under specified triggers (rating downgrade, regulatory action, etc.).

**A7: CLO mezzanine tranches.** CLO issuer is the liability side; insurer (or other investor) holds. Tradeable but illiquid in stress; non-redeemable.

**A8: Money market fund shares.** MMF is the liability side; holder is the asset side. Daily redeemable at NAV (1.00 for stable, floating for institutional prime since 2014 reform).

**A9: Bank deposits.** Bank issues, holder holds. Demand or term.

**A10: Government securities (Treasuries, agency MBS).** Treasury or GSE issues; portfolio of holders. Tradeable in deep markets.

**A11: Equity claims (common and preferred stock).** Stockholders hold; issuer's equity. Tradeable, not redeemable.

**A12: Other liabilities (residual).** Catch-all for liabilities not classified elsewhere. The "other liabilities" line on insurer balance sheets — which grew $11.6B at MetLife in three quarters of 2025 — sits here pending decomposition.

### 5. Real-dollar capacity tiers (the breaking-point side)

Following the discussion in REGULATORY_ARBITRAGE.md but formalized here:

**Tier 1 — Settlement-final cash.** Federal Reserve reserves, currency, Treasury bills. Real dollars by any definition. Not contingent on anyone else's solvency or market functioning.

**Tier 2 — Convertible to Tier 1 under normal market conditions.** Treasury notes/bonds (subject to small haircut for duration risk), agency MBS (subject to deeper haircut in stress), GSE debt, demand deposits at solvent banks, prime MMF shares (post-2014 reform: floating NAV institutional MMFs, par-redeemable stable retail MMFs).

**Tier 3 — Convertible only via secondary-market sale or counterparty performance, conditional on the network functioning.** FABS, FABNs, FABCP, repo positions, FHLB advances (callable but not unilaterally redeemable), securities-lending cash collateral, CLO mezzanine, private credit, CRE loans, alternatives.

**Tier 4 — Equity and equity-equivalents.** Common stock, preferred stock, residual interests.

The real-dollar capacity at node $i$, denoted $c_i$, is defined as Tier 1 holdings plus the Tier 2 holdings adjusted for stressed haircuts. The stressed haircuts come from the Federal Reserve's CCAR/DFAST severely adverse scenario tables (calibrated by asset class), supplemented by the OFR's bank-stress-scenario haircut tables and the IMF GFSR sensitivity analyses.

### 6. Runnability classification (for cascade rules)

Each arc carries a runnability profile:

- **Time-to-payable.** Minimum time from holder's redemption demand to payment due. MMF shares: same day (T+1 settlement). FABCP: at maturity (typically <30 days) or via put. XFABS: at next put date. Term FABN: at maturity. FHLB advances: at maturity (not redeemable at holder option but callable at issuer option for some structures). Repo: at maturity (typically overnight to 90 days). Sec-lending cash collateral: at recall (open-ended). Reinsurance: contingent on cession contract triggers, typically not redeemable at holder option.
- **Put-option-at-stress.** Does the holder have an embedded option to demand early redemption under stress conditions (rating downgrade, market dislocation)? XFABS yes; standard FABN no.
- **Collateral-based recourse.** Does the holder have collateral recourse independent of the issuer's solvency? Repo yes (collateral can be liquidated); FHLB advances yes (super-lien position); FABN no; funding agreement no (claim against general account, in priority above general creditors but below policyholders for traditional life policies — though for FABN, the funding agreement is *senior* to traditional policies in some jurisdictions, a key reason FABN is rated AAA despite the insurer's own rating).

The runnability profile is what makes the cascade rules instrument-specific. A 5% redemption shock to MMF shares triggers immediately; a 5% shock to FHLB advance demand only matters at maturity dates; a 5% shock to in-force life policies triggers the contractual surrender procedure, often weeks or months. Aggregating these across arcs without distinguishing time horizons is what makes naive systemic-risk analyses miss the point.

---

## Part III — The graph structure

### 7. The three overlay graphs

The network is not a single graph; it is **three coupled graphs on the same node set**.

**G1: The funding-flow graph.** Directed multigraph. Nodes from §3. Arcs from §4. Arc weights are dollar volumes at time $t$. Solved via the constraint system in §1.

**G2: The supervisory-coverage graph.** Bipartite graph. One side is operating entities (M1–T3); the other side is regulators (R1–R11). Arcs indicate "supervises." Multiple regulators may supervise different aspects of the same entity (e.g., a BHC subsidiary is supervised by both FRB at the BHC level and OCC at the national bank level). Edge weight = 1 if direct supervision, 0.5 if indirect/joint supervision. Used to compute the **regulatory-discontinuity depth** of any path in G1: the number of distinct regulators a dollar of claim flows through from its M-side origin to its T-side terminal.

**G3: The ownership/affiliation graph.** Directed graph. Operating entities point to their controlling parent. Apollo → Athene (control); Apollo → MidCap Financial (control, CLO manager); Apollo → ATLAS Capital (control, AAM). Plus affiliation arcs (board overlaps, management agreements, sub-advisory arrangements). SEC Form ADV's Part 1A relational data, SEC 10-K affiliate disclosures, and NAIC's Insurance Holding Company System filings are the data sources.

**Coupled analysis.** A *closed loop* in the network is a cycle in G1 (funding flow) that lies entirely within a single connected component of G3 (ownership cluster). These represent the "Bermuda Triangle" / PE-affiliated structures where the same parent earns fees on every step of the chain. The total dollar volume of closed loops, broken out by ownership cluster, is a primary output of CLAIM-WEB.

### 8. The from-whom-to-whom matrix representation

Following Shrestha-Mink-Fassler (2012) and the IMF's FWTW framework, for each instrument $k$ at each time $t$ we maintain a square matrix $W^k(t)$ where $W^k_{ij}(t) = x_{ij}^k(t)$ — issuer $j$, holder $i$, instrument $k$. The full network state is the stack of these matrices $\{W^k(t)\}_{k \in K}$.

The from-whom-to-whom representation is essential because:

- Aggregations are straightforward (sector-level FWTW = sum the entity-level matrix over sectoral indices)
- The Z.1 sectoral constraints (Law 3) are row and column sums of the aggregated FWTW
- The Anand-Craig-von Peter estimation operates directly on FWTW matrices
- The Sankey visualization is a natural rendering of FWTW

### 9. Time dimension

All matrices are quarterly. We target a panel from **2000-Q1 through current quarter**, which covers:

- The 2000–2007 run-up period (FABS market growth)
- The 2007 XFABS run (validation episode #1)
- The 2008 AIG securities-lending collapse (validation episode #2)
- The 2009–2019 expansion period (FHLB advances to insurers ramping)
- The March 2020 COVID stress (validation episode #3)
- The 2020–present period (PE-affiliated insurer rise; Bermuda cession growth; current state)

Quarterly cadence is the highest frequency at which the full constraint set is publicly available. (NAIC Schedule S is annual; Z.1 is quarterly; SEC XBRL is quarterly; FHLB Combined Financial Report is quarterly; SEC Form NMFP is monthly but aggregated to quarterly for consistency.) An intra-quarter daily reconstruction is *feasible* for the FABS data (the EFA FABS dataset is daily) and the FHLB data (advances change daily but Combined Financial Report is quarterly snapshot), and would be useful for the March 2020 retrodiction; this is in scope.

---

## Part IV — Data sources and acquisition

### 10. Primary data sources

Each data source is identified by acquisition method, refresh cadence, license terms (we use only free origin sources — paid aggregators like Capital IQ Pro, Moody's CreditView, LCD are explicitly excluded except where their methodology is published and we replicate it from primary sources), and the arcs / nodes / constraints it populates.

#### 10.1 Federal Reserve Z.1 — Financial Accounts of the United States

URL: `https://www.federalreserve.gov/releases/z1/`

Tables relevant to CLAIM-WEB:
- L.116 — U.S. life insurance companies (assets and liabilities, by instrument)
- L.117 — Private and federal pension funds
- L.121 — Money market funds (assets and liabilities)
- L.122 — Mutual funds
- L.124 — Exchange-traded funds
- L.207 — Open market paper (commercial paper, including FABCP)
- L.208 — Debt securities (FABN and similar)
- L.210 — Treasury securities
- L.211 — Agency- and GSE-backed securities (including FHLB consolidated obligations)
- L.213 — Corporate and foreign bonds
- L.214 — Loans
- L.215 — Mortgages
- L.226 — Repurchase agreements
- L.227 — Reverse repurchase agreements

Refresh: Quarterly, approximately 75 days after end-of-quarter.
Format: Tab-separated text files in archive; structured CSV in FRED.
Acquisition: FRED API (free) for the structured form; direct download from `federalreserve.gov/releases/z1/current/` for the most recent.

What it provides: **Law 3 sectoral constraints**. Total holdings by sector for every instrument we model.

#### 10.2 SEC XBRL company-facts API (already in FSR Dashboard fetchers)

URL: `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json`

Refresh: As filed (quarterly for 10-Q, annually for 10-K).
Format: JSON with us-gaap + custom-namespace tagged facts.
Acquisition: HTTP GET with User-Agent header.

What it provides: Per-entity balance sheet aggregates at quarterly cadence. The marginals of each insurer's, bank's, AAM-holding-company's, and FHLB district's balance sheet.

Specific items extracted:
- Total assets, liabilities, equity (Laws 1)
- `SecuritiesSoldUnderAgreementsToRepurchase` (A4 arc, issuer side)
- `PayablesForCollateralUnderSecuritiesLoanedAndOtherTransactions` (A5 arc, issuer side)
- `AdvancesFromFederalHomeLoanBanks` (A3 arc, issuer side, where disclosed)
- `PolicyholderAccountBalance` with dimension `CapitalMarketsInvestmentProductsAndStableValueGICs` or equivalent (A1 arc, issuer side)
- Investment portfolio composition (Schedule of investments, partial — A7, A10, A11 holdings)

Full list and tag mapping by entity in the data dictionary (Part VI).

#### 10.3 NAIC statutory annual statements (Schedule S, D, BA, DB)

URL: NAIC filings are intermediated through state insurance department portals; the NAIC itself does not publish them centrally for free. However, individual filings are accessible per-state.

**Schedule S — Reinsurance.** Ceded reinsurance broken out by counterparty (name, NAIC code, jurisdiction), instrument (life vs A&H vs annuity), and amount. The data source for A6 arc and T2 nodes.

**Schedule D Part 1 — Long-term bonds.** Security-by-security holdings for fixed-income investments. Provides A7 holdings (CLO mezzanine), A10 (Treasuries), and segments of A12 (corporate bonds).

**Schedule BA — Other long-term invested assets.** Alternative investments, partnerships, joint ventures. Critical for measuring the illiquid asset side.

**Schedule DB — Derivatives.** Used to identify securities-lending and repo positions on the statutory side.

Refresh: Annual (filed March 1 of following year for prior year-end).
Format: Statutory filings; structured XBRL since 2010 but not always machine-parseable.
Acquisition: Per-state insurance department portal scraping plus optical character recognition where needed; the project will build a free `NaicStatutoryFetcher` that aggregates across state portals.

What it provides: Annual snapshot of insurer balance sheets at full granularity (security-by-security on Schedule D). Quarterly statutory statements provide aggregate but not security-level detail.

#### 10.4 FHLB Office of Finance Combined Financial Report

URL: `https://www.fhlb-of.com/ofweb_userWeb/pageBuilder/fhlbank-financial-data-36`

Refresh: Quarterly (approximately 60–90 days after end-of-quarter).
Format: PDF with structured tables.
Acquisition: Direct download of PDF, structured-table extraction via `tabula-py` or `pdfplumber`.

What it provides:
- Total FHLB advances outstanding (system-wide, quarterly): Law 3 / 2 constraint
- Member-type breakouts: depository, insurance, CDFI. Insurance-share of total → key input for A3 arc aggregate sizing
- Top 10 advance-holders by member: where disclosed, populates A3 arc weights for the largest insurer borrowers

Supplemented by individual FHLB district 10-K and 10-Q filings (SEC EDGAR), which provide district-level advance composition and the top-10 lists per district. Aggregating across 11 districts gives us essentially the entire A3 arc structure.

#### 10.5 SEC Form NMFP — Money Market Fund holdings

URL: SEC EDGAR Form NMFP filings.

Refresh: Monthly (filed 5 days after end-of-month).
Format: XML.
Acquisition: SEC EDGAR full-text search + per-filing XML download.

What it provides: Security-by-security portfolio holdings for every money market fund. Includes CUSIPs of FABN holdings. Aggregating MMF holdings of FABN by SPV issuer gives us the A8/A2 arc structure on the MMF side directly. Cross-references with SPV-issuer FABN totals (from FRB EFA dataset) for double-entry consistency check.

#### 10.6 SEC Form ADV — Investment Adviser registration

URL: SEC IAPD (Investment Adviser Public Disclosure) database.

Refresh: At update.
Format: Structured database with Part 1A (relational) and Part 2 (brochure).
Acquisition: IAPD bulk download (free).

What it provides: AAM-to-affiliate registry. Part 1A Schedule R discloses related entities. Provides the G3 ownership graph for AAM-affiliated insurers, CLO managers, BDCs, and offshore reinsurers.

#### 10.7 SEC Form 13F — Institutional Investment Manager holdings

URL: SEC EDGAR Form 13F filings.

Refresh: Quarterly (45 days after end-of-quarter).
Format: XML.
Acquisition: SEC EDGAR per-filer 13F-HR download.

What it provides: Public security holdings ≥ $200,000 in value or ≥ 10,000 shares by managers with > $100M AUM. Used to populate intra-AAM-cluster public security cross-holdings.

#### 10.8 SEC Form X-17A-5 (FOCUS) — Broker-Dealer financial and operational reports

URL: SEC EDGAR.

Refresh: Quarterly.
Format: Structured filings (variable historical, FOCUS-X for modern filers).
Acquisition: SEC EDGAR per-broker-dealer.

What it provides: Broker-dealer-level repo, sec-lending, and prime brokerage exposures. Critical for I4 (dealer banks) since the broker-dealer subsidiary holds the repo book, not the BHC parent.

#### 10.9 FRB Enhanced Financial Accounts — FABS dataset

URL: `https://www.federalreserve.gov/releases/efa/efa-project-funding-agreement-backed-securities.htm`

Refresh: Daily series; aggregated to quarterly.
Format: Time-series CSV.
Acquisition: Direct download.

What it provides: Daily outstanding amounts of FABN (medium-term notes), FABCP (commercial paper), and XFABS broken out by maturity bucket. Foley-Fisher / Meisenzahl / Narajabad / Perozek / Verani (2016) is the methodology paper. Provides the *aggregate* A2 arc weight, which serves as a sectoral constraint and a sanity check against the SPV-level reconstruction.

#### 10.10 FIO Annual Report to Congress

URL: `https://home.treasury.gov/policy-issues/financial-markets-financial-institutions-and-fiscal-service/federal-insurance-office`

Refresh: Annual.
Format: PDF.
Acquisition: Direct download.

What it provides: Cross-cutting commentary on offshore reinsurance, PE-affiliated insurers, and macroprudential insurance issues. Quantitative tables on Bermuda cessions, insurer asset composition.

#### 10.11 OFR data collections

The OFR's non-centrally cleared bilateral repo (NCCBR) data collection began December 2024. The data is supervisory and not publicly available at entity level. The OFR publishes aggregate statistics; we use those as sectoral constraints (Law 3 augmentation).

#### 10.12 Bermuda Monetary Authority public registers

URL: `https://www.bma.bm/`

Refresh: Annual statutory filings by Bermuda-domiciled insurers.
Format: PDFs.
Acquisition: BMA register search + per-entity filing download.

What it provides: Bermuda-side disclosure for the largest offshore reinsurers (Athene Life Re, Global Atlantic's Bermuda affiliates, etc.). Provides the asset-side of T2 nodes where the U.S. NAIC Schedule S only provides the liability-side amount of cession.

#### 10.13 Treasury TIC (Treasury International Capital) data

URL: Treasury Department.

What it provides: Foreign holdings of U.S. financial instruments (A2 by foreign holder, A11 cross-border equity, A10 foreign Treasury holdings). Populates the M5 source-of-funds node.

### 11. Data acquisition schedule and the master fetcher architecture

A separate fetcher class per data source, each emitting normalized records into a unified store. The architecture:

```
claimweb/
├── fetchers/
│   ├── base.py           # AbstractFetcher with retry, rate-limit, cache
│   ├── z1.py             # Federal Reserve Z.1 fetcher
│   ├── sec_xbrl.py       # SEC companyfacts (reused from FSR Dashboard)
│   ├── sec_nmfp.py       # SEC Form NMFP MMF holdings
│   ├── sec_adv.py        # SEC IAPD investment adviser data
│   ├── sec_13f.py        # SEC Form 13F holdings
│   ├── sec_focus.py      # SEC Form X-17A-5 broker-dealer FOCUS
│   ├── sec_nXXa.py       # SEC Form N-54A/C BDC elections
│   ├── naic_schedule_s.py  # NAIC Schedule S reinsurance ceded
│   ├── naic_schedule_d.py  # NAIC Schedule D security-by-security holdings
│   ├── naic_schedule_ba.py # NAIC Schedule BA alternative investments
│   ├── naic_schedule_db.py # NAIC Schedule DB derivatives
│   ├── fhlb_combined.py   # FHLB Office of Finance Combined Financial Report
│   ├── fhlb_district.py   # 11 FHLB district 10-Q/10-K filings
│   ├── frb_efa_fabs.py    # FRB Enhanced Financial Accounts FABS
│   ├── fio_annual.py      # FIO Annual Report tables
│   ├── ofr_publications.py # OFR working papers and aggregate data
│   ├── bma_register.py    # Bermuda Monetary Authority registers
│   ├── treasury_tic.py    # Treasury TIC data
│   └── ffiec_y9c.py       # FFIEC Y-9C bank holding company reports
```

Each fetcher writes to a unified `claimweb/data/raw/{source}/{entity_id}/{period}.json` store and a normalized arc-fact store `claimweb/data/normalized/arcs/{period}.parquet`.

### 12. Data quality flagging

Every arc weight in the final solved network carries a `data_quality` enum:

- **DIRECT_MEASURED** — directly observed via XBRL or other origin disclosure
- **MARGINAL_INFERRED** — solved from balance sheet identity (Law 1) given measured row/column sums
- **DOUBLE_ENTRY_INFERRED** — solved from Law 2 given one side measured
- **SECTORAL_DISAGGREGATED** — disaggregated from a sectoral total (Law 3) via maximum-entropy / minimum-density bracketing
- **PROXY** — estimated from a closely related instrument (e.g., total Level 2 HQLA as a proxy for FABS holdings within bank treasuries)
- **MODEL_ESTIMATE** — derived from a calibrated model with documented assumptions
- **UNOBSERVED** — flagged but reported as missing; the model does not invent these

This metadata travels with every output. A user querying any arc gets both the dollar weight and the provenance.

---

## Part V — The model

### 13. Network reconstruction algorithm

For each quarter $t$ from 2000-Q1 through current:

#### Phase A — Direct measurement ingestion

1. Run all fetchers for period $t$. Collect:
   - Direct arc measurements $\hat{x}_{ij}^k(t)$ where disclosed
   - Marginal totals $\hat{r}_i^k(t) = \sum_j x_{ij}^k(t)$ and $\hat{c}_i^k(t) = \sum_j x_{ji}^k(t)$ from each entity's balance sheet
   - Sectoral aggregates $\hat{Z}_{s,k}(t)$ from Z.1
   - Entity-level total balance sheets $\hat{A}_i(t), \hat{L}_i(t), \hat{E}_i(t)$

2. Apply Law 1 (balance sheet identity) at each entity. Flag any entity for which $|\hat{A}_i(t) - \hat{L}_i(t) - \hat{E}_i(t)| > $ tolerance (typically 0.5% of total assets — accounting differences accumulate). Investigate flagged entities; resolve via 10-K reconciliation footnotes.

#### Phase B — Constraint compilation

Build the constraint matrix $C$ and constraint vector $b$ such that $C \cdot \text{vec}(X) = b$ captures all Laws 1, 2, 3 in linear form. Direct measurements appear as equality constraints fixing specific arcs.

Add inequality constraints from prior knowledge:
- All arc weights non-negative
- Entity-type compatibility constraints (an MMF cannot hold a CLO mezzanine tranche directly; an FHLB cannot make an advance to a non-member; etc.)

#### Phase C — Network reconstruction (the under-determined part)

Solve twice:

**C.1 — Maximum-entropy reconstruction** (Upper 2004 baseline):
$$\hat{X}^{ME} = \arg\max_X \left( -\sum_{ij,k} x_{ij}^k \log x_{ij}^k \right) \quad \text{s.t.} \quad C \cdot \text{vec}(X) = b, \; X \geq 0$$
Solved via iterative proportional fitting (RAS algorithm) for tractability; verified with cvxpy convex solver for small subnetworks.

**C.2 — Minimum-density reconstruction** (Anand-Craig-von Peter 2015):
A combinatorial relaxation that places probability mass on the smallest number of arcs consistent with the marginals. Uses the published algorithm with the heuristic implementation in `NetworkRiskMeasures` (R) or our own Python port.

For each arc, report:
- $\hat{x}_{ij}^{k, ME}$ — maximum-entropy estimate
- $\hat{x}_{ij}^{k, MD}$ — minimum-density estimate
- $[\min, \max]$ across the two methods — the *structural uncertainty band*

This is exactly Anand-Craig-von Peter's recommended methodology and provides scientifically defensible uncertainty quantification.

#### Phase D — Flow-of-funds reconciliation

For each quarterly transition $t \to t+1$, verify:
$$\Delta \hat{X}(t \to t+1) = \hat{F}(t \to t+1) + \hat{R}(t \to t+1)$$
where $\hat{F}$ is the Z.1 flow-table-derived expected transaction volume and $\hat{R}$ is the implied revaluation. Discrepancies are reported and flagged.

#### Phase E — Output

The solved network $\hat{X}(t)$ with provenance metadata per arc is written to:
- `claimweb/output/network/{period}/arcs.parquet` — the full from-whom-to-whom matrix
- `claimweb/output/network/{period}/nodes.parquet` — node-level totals and capacities
- `claimweb/output/network/{period}/quality_report.json` — coverage, consistency, residual

### 14. Claim-multiplier computation

For each period $t$:

**System-level claim multiplier:**
$$M(t) = \frac{\sum_{ij,k \in F} \hat{x}_{ij}^k(t)}{\text{Real underlying asset base}(t)}$$
where $F$ is the set of financial arcs (excluding equity), and the denominator is the value of underlying non-financial assets ultimately supporting the chain (real estate, mortgage loans to actual properties, productive business loans) — what Z.1 calls "tangible assets" plus the equity claims on real production.

**Per-cluster claim multipliers** for ownership clusters in G3 (Apollo cluster, Blackstone cluster, etc.):
$$M_g(t) = \frac{\text{intra-cluster financial claims}(t)}{\text{cluster's real underlying assets}(t)}$$

**Per-instrument claim chain lengths:** for each instrument $k$, the average number of intermediating arcs between a source-of-funds node and a terminal-exposure node along paths that include instrument $k$.

### 15. Breaking-point analysis (the Eisenberg-Noe + fire-sale cascade)

For each chosen shock specification $\Delta r$ (entry node + instrument + magnitude):

#### Phase F — Eisenberg-Noe clearing

Apply Eisenberg-Noe (2001) to compute the clearing payment vector $p^*$:
- Initialize $p^{(0)} = \bar{p}$ (full liability vector)
- Iterate $p^{(n+1)}_i = \min(\bar{p}_i, c_i - \Delta r_i + \sum_j \pi_{ji} p^{(n)}_j)$
- Converges to fixed point $p^*$ in polynomial time
- Identify defaulting nodes: $\{i : p^*_i < \bar{p}_i\}$

#### Phase G — Fire-sale extension (Cont-Schaanning 2017)

When defaulting nodes hold illiquid assets that must be liquidated:
- Compute liquidation volume per asset class
- Apply inverse demand function (calibrated from Duarte-Eisenbach 2021 / Greenwood-Landier-Thesmar 2015) to compute price impact
- Mark down all holders' portfolios at the new price
- Update real-dollar capacities $c_i$ — some nodes that were not initially defaulting are now defaulting
- Iterate to fixed point of the combined direct + indirect cascade

The fire-sale extension is critical because the illiquid asset side of the insurer general account (CLO mezzanine, CRE loans, alternatives) is exactly where price impact is severe. A naive Eisenberg-Noe without fire sales will understate the cascade because most insurers can pay their direct liabilities; what they can't do is monetize their illiquid asset book at par.

#### Phase H — Multi-regime constraint binding (Coen-Lepore-Schaanning 2019)

Each node has potentially multiple binding regulatory constraints:
- LISCC banks: CET1, LCR, SLR, NSFR
- Insurers: RBC, AAT (Actuarial Asset Adequacy Test)
- FHLB: FHFA capital requirement
- Offshore reinsurers: BMA Economic Balance Sheet / CIMA prescribed regime

The cascade simulation respects all binding constraints — a node that breaches *any* constraint must take action (raise capital, deleverage, request waiver). This produces meaningfully different cascade patterns than a single-constraint model.

#### Phase I — Output

For each shock specification, output:
- The clearing payment vector $p^*$
- The set of defaulting nodes
- The fire-sale price impact per asset class
- The total real-dollar shortfall
- The cascade depth (longest chain of induced defaults)
- The breaking-point threshold $\theta^*$ (the smallest shock magnitude that causes any default)
- The propagation map (DAG showing which node failed when due to which other node's failure)

### 16. The DebtRank overlay

In parallel with the cascade simulation, compute DebtRank (Battiston et al. 2012) on the solved network. DebtRank measures *distress propagation* without requiring default — a node that experiences distress propagates that distress through its liabilities even if it does not formally default.

DebtRank for our network: for each node $v$ as the source of distress, compute the total weighted distress propagated to all other nodes through the network's arc structure. The DebtRank vector identifies the *systemically important nodes* — those whose distress (not default) has the largest network impact.

This complements the breaking-point analysis: the breaking-point identifies the *threshold*; DebtRank identifies *which nodes matter most for stability* at sub-threshold stress.

### 17. Historical validation

The model must retrodict three historical episodes within reasonable error bars:

**Validation #1 — Summer 2007 XFABS run.** From the published Foley-Fisher / Narajabad / Verani (2020) data, the run on extendible FABS in 2007-Q3 totaled approximately $18B. Given the network state at 2007-Q2 (reconstructed by CLAIM-WEB from then-current data) and a shock specification of "institutional MMF and bank holders refuse to extend XFABS at next reset date," the cascade simulation should reproduce a loss within ±30% of the historical $18B and identify the specific insurers that experienced the run (Hartford, ING USA, MetLife, Prudential, AIG SunAmerica).

**Validation #2 — Fall 2008 AIG securities-lending collapse.** From McDonald and Paulson (2015), Peirce (2014), and Foley-Fisher / Gissler / Verani (2019), AIG's securities-lending program collapse was the proximate trigger for the federal bailout, with losses concentrated in AIG's life insurance subsidiaries. Given 2008-Q2 network state and a shock specification of "borrowers refuse to return collateral to AIG sec-lending program at scheduled return dates," the cascade simulation should reproduce a loss within ±30% of the historical $20–25B and identify AIG as the central node.

**Validation #3 — March 2020 prime MMF / repo intermediation stress.** From multiple FRB and academic post-mortems, the March 2020 stress was triggered by simultaneous prime MMF redemptions and dealer-bank repo intermediation pullback. Insurers responded by drawing aggressively on FHLB advances (a $20B+ quarterly increase) and stable value GICs experienced visible stress. Given 2020-Q1 network state and a shock specification of "30% prime MMF investor redemptions + 50% dealer repo intermediation reduction simultaneously," the cascade simulation should reproduce the qualitative pattern (FHLB advance surge, stable value stress, no insurer default) and the FHLB advance increase within ±20%.

A model failing any of the three validations is not deployed. The model is *re-parameterized* (cascade rules, recovery rates, fire-sale price-impact parameters) until validation succeeds, then *frozen*, then forward-tested on the post-2024 period as a holdout.

---

## Part VI — Implementation

### 18. Codebase architecture

```
claimweb/
├── README.md
├── PROJECT_PLAN.md                  # This document
├── METHODOLOGY.md                   # Formal mathematical specification
├── LITERATURE.md                    # Annotated bibliography (§2)
├── claimweb/
│   ├── __init__.py
│   ├── fetchers/                    # §11 — one module per data source
│   ├── normalize/                   # §10 — schema normalization
│   ├── constraints/                 # §13 Phase B — constraint compilation
│   │   ├── kcl.py                   # Law 1 (balance sheet identity)
│   │   ├── double_entry.py          # Law 2 (instrument-level conservation)
│   │   ├── sectoral.py              # Law 3 (Z.1 aggregates)
│   │   ├── flow_funds.py            # Law 4 (transactions vs positions)
│   │   └── prior.py                 # entity-type compatibility constraints
│   ├── reconstruct/                 # §13 Phase C — network solver
│   │   ├── max_entropy.py           # Upper 2004 / Anand-Craig-von Peter ME
│   │   ├── min_density.py           # Anand-Craig-von Peter MD
│   │   ├── solver.py                # The harness that runs both and brackets
│   │   └── validate.py              # internal consistency checks
│   ├── cascade/                     # §15 — Eisenberg-Noe + extensions
│   │   ├── eisenberg_noe.py         # the canonical clearing-vector algorithm
│   │   ├── fire_sale.py             # Cont-Schaanning indirect contagion
│   │   ├── multi_constraint.py      # Coen-Lepore-Schaanning multi-regime
│   │   ├── contingent.py            # Banerjee-Feinstein for reinsurance arcs
│   │   └── debtrank.py              # Battiston et al. DebtRank centrality
│   ├── multiplier/                  # §14 — claim multiplier computations
│   ├── validation/                  # §17 — historical retrodiction
│   │   ├── ep1_2007_xfabs.py
│   │   ├── ep2_2008_aig_seclending.py
│   │   └── ep3_2020_covid_stress.py
│   ├── visualize/                   # Part VII — output rendering
│   │   ├── sankey.py
│   │   ├── network_link.py
│   │   ├── cascade_dag.py
│   │   └── multiplier_timeseries.py
│   └── api/                         # Part VIII — query / drill-down API
├── data/
│   ├── raw/                         # per-source raw data
│   ├── normalized/                  # arc-fact store
│   └── output/                      # solved networks per period
├── docs/                            # Sphinx-built methodology documentation
├── notebooks/                       # exploratory analysis (not for production)
├── tests/                           # pytest suite, target >90% coverage
└── pyproject.toml
```

### 19. Dependencies

Core: `numpy`, `scipy`, `pandas`, `networkx`, `cvxpy`, `pyarrow` (parquet I/O).
Statistical: `statsmodels`, `scikit-learn`.
Plotting: `matplotlib`, `plotly` (for interactive Sankey), `pyvis` (for interactive network).
Data acquisition: `httpx`, `requests`, `beautifulsoup4`, `pdfplumber`, `tabula-py`, `lxml`.
Optimization: `cvxpy` (for the entropy formulation), `pyomo` (for larger problems if needed), `gurobipy` (commercial; we will not require it but support it for fast solves where institutional users have a license).
Testing: `pytest`, `hypothesis` (property-based testing for the conservation laws).

### 20. Computational scale

A single quarterly reconstruction:
- Z.1 ingest: ~10MB, 1 minute
- SEC XBRL for ~30 entities: ~500MB, 30 minutes
- NAIC Schedule S/D/BA: ~100MB, 1 hour (most expensive; involves PDF parsing of statutory filings)
- FHLB and FRB EFA: ~50MB, 5 minutes
- Constraint compilation: ~10 seconds
- Maximum-entropy solve: ~1 minute for the ~5000 unknowns
- Minimum-density solve: ~10 minutes (combinatorial relaxation)
- Output: ~10MB

Total per quarter: ~2 hours wall-clock for full pipeline. Across 100 quarters (2000-Q1 through 2024-Q4): ~200 hours of compute, parallelizable to ~10 hours on a 20-core workstation. Tesla's existing hardware handles this comfortably.

Cascade simulations are fast (Eisenberg-Noe is O(n²) per iteration, converges in O(n) iterations; fire-sale extension adds a constant factor). Running ~1000 shock scenarios across all 100 quarters takes ~10 hours on the same hardware.

### 21. Testing discipline

Every module has a test file with:
- Unit tests for individual functions
- Property-based tests verifying the conservation laws hold for any random valid input (using `hypothesis`)
- Integration tests verifying that synthetic networks with known structure are correctly reconstructed (sanity checks against networks where the answer is computable by hand)
- Validation tests for the three historical episodes (these run against frozen historical data and verify model output against published numbers)

Coverage target: 95%+ on `claimweb/` (the analytical modules). The fetchers tolerate lower coverage because external data sources cannot be fully mocked.

The conservation laws are *invariants* — any output that violates them is a bug. The test suite asserts the invariants hold on every solved network, at every period, for every entity.

---

## Part VII — Outputs and visualization

### 22. The five primary outputs

**Output 1: The solved network dataset.** Quarterly from 2000-Q1 through current quarter. Released as Parquet files plus a CSV mirror for accessibility. Each row: (period, source_node_id, target_node_id, instrument_class, dollar_amount_me, dollar_amount_md, data_quality_flag, provenance_source). Approximately 50–100GB across the full panel (compressed Parquet). Released under an open-data license.

**Output 2: The claim multiplier time series.** For the system, per ownership cluster, per instrument class. Released as CSV; visualized as line charts with uncertainty bands.

**Output 3: The cascade-simulation result database.** For each (period, shock specification), the full cascade output. Approximately 1000 baseline shock scenarios per period; an interactive endpoint allows users to specify additional scenarios. Released as Parquet; visualized via the cascade-DAG renderer.

**Output 4: The Sankey visualization.** Static + interactive. For each period, a Sankey of the network with arcs sized by dollar volume, nodes color-coded by ownership cluster and shaded by real-dollar-capacity ratio. Supports time-slider navigation across 2000-Q1 through current. Built in Plotly + D3.

**Output 5: The methodology paper.** Approximately 60–80 pages. Sections covering: motivation (the regulatory-arbitrage framing); the conservation-circuit formalism; data sources and acquisition; the network reconstruction algorithm; the cascade analysis; historical validation; and applications. Submitted for peer review at *Journal of Financial Economics*, *Review of Financial Studies*, or *Journal of Finance*. Pre-print on SSRN and arXiv.

### 23. Documentation deliverables

In addition to the methodology paper:

- **A standalone technical handbook** covering implementation details for analysts who want to use the data and tools. Approximately 100 pages.
- **A user-facing summary report** for policymakers and the financial press. Approximately 20 pages. Plain-English explanation of the framing and the key findings.
- **A data dictionary** specifying every node, every arc, every instrument with their definitions and data sources. Approximately 50 pages, structured Markdown for machine-readability.
- **A reproducibility package** — a Docker container with all dependencies pinned, a `make all` target that reproduces the entire dataset and all figures in the paper from raw inputs to final outputs. Required for top-tier journal submissions.

### 24. The interactive web product

A live web product at a domain TBD. Features:

- Browse the network at any quarter from 2000-Q1 through current
- Toggle between Sankey and node-link views
- Zoom from sector aggregation to entity granularity to legal-entity granularity
- Overlay G2 (regulatory coverage) or G3 (ownership clusters)
- Filter by instrument class, by entity, by AAM cluster
- Simulate custom shocks: select an entry node, specify a shock magnitude, see the cascade play out in animation
- Drill down on any arc: see its dollar volume, provenance, data quality flag, the source filing
- Download any subset as CSV
- View the historical retrodiction overlaid on the actual 2007 / 2008 / 2020 outcomes

Built as a static-site-generation + server-side cascade-API hybrid. Frontend in React + D3. Backend in FastAPI serving the cascade simulations on demand.

---

## Part VIII — Validation, peer review, and dissemination

### 25. The validation gauntlet

Before any output is published, the system passes:

**Internal validation:**
- Every solved network passes all conservation-law checks (Laws 1–4)
- Every cascade simulation passes monotonicity checks (larger shocks produce weakly larger cascades)
- The maximum-entropy and minimum-density brackets are non-overlapping with directly measured arcs

**Historical validation:**
- The three historical episode retrodictions pass within their specified tolerance bands (§17)

**Cross-validation against external estimates:**
- Total NTL aggregate matches the FSR's published $531B for 2025-Q4 within ±10%
- Total FHLB advances to insurers matches FHLB published total within ±2%
- Total Bermuda cession matches Bloomberg / S&P published aggregates within ±10%
- The Foley-Fisher et al. published FABS outstanding matches our reconstruction within ±5%

**Expert review:**
- Pre-submission review by at least three external experts: one from the FRB Foley-Fisher / Verani group; one from the academic systemic-risk literature (a candidate: Stéphane Verani, Zachary Feinstein, Rama Cont, or Sasha Acemoglu); one from industry (e.g., NAIC research; AM Best; an insurer chief risk officer)
- Reviewer comments addressed in writing; revised draft re-reviewed

### 26. Peer review and academic publication

Target venues, in priority order:
1. *Journal of Finance* (most prestigious; competitive)
2. *Review of Financial Studies*
3. *Journal of Financial Economics*
4. *Management Science* (the home journal of Eisenberg-Noe 2001; well-suited methodologically)
5. *Quantitative Finance* (home of Anand-Craig-von Peter 2015)

The paper's contribution claims:
1. First application of the conservation-circuit / clearing-vector / fire-sale combined framework to the U.S. life insurance regulatory-arbitrage network at entity-level granularity
2. First reconstruction of the FABS-FHLB-Bermuda-CLO chain from origin public data without paid-aggregator dependencies
3. The historical retrodiction of three known crisis episodes serves as out-of-sample validation
4. Provides public infrastructure for ongoing monitoring of the network
5. The minimum-density / maximum-entropy bracketing provides defensible uncertainty quantification on every reported quantity

### 27. Open-source release

All code released under MIT or Apache 2.0 license. Public repository at `github.com/[org]/claimweb`. The full dataset hosted on a permanent archive (Zenodo with DOI; institutional repository at a university partner). The interactive web product hosted on a stable domain with at least 5-year commitment.

### 28. Regulator and policymaker engagement

In parallel with academic publication:
- Briefing to the FRB Financial Stability Division (the authors of the FSR)
- Briefing to OFR research staff
- Briefing to FIO at Treasury
- Briefing to NAIC's Macroprudential (E) Working Group
- Briefing to FSB Nonbank Financial Intermediation working group

These briefings are not for endorsement (we are not requesting that); they are to ensure regulators with mandate know the tool exists and can use it as a complement to their internal systems.

### 29. Press and public engagement

A coordinated launch: methodology paper preprint, web product live, accompanying explainer for the financial press. Targeted outreach to:
- Bloomberg (continuation of their November 2025 Athene-Apollo series)
- *Financial Times* (covered FSB private credit report)
- *Risk.net*
- *Wall Street Journal*
- *Retirement Income Journal* (the venue that established the "Bermuda Triangle" framing)

The web product is built to be screen-recordable and embeddable; the press kit includes pre-rendered video walkthroughs and high-resolution figure exports.

---

## Part IX — Risks, threats, and mitigation

Every project of this scope has failure modes. The serious ones, with mitigations:

### 30. Data acquisition risks

**Risk: SEC EDGAR rate-limiting or terms-of-service changes.** SEC currently requires a User-Agent header but does not impose hard rate limits beyond ~10 requests per second. We mitigate by caching aggressively, by spreading acquisition across time, and by maintaining a mirror of acquired raw data so re-fetching is not required for incremental updates.

**Risk: NAIC statutory filings are not freely centralized.** Each state insurance department hosts its filings separately, with varying access regimes. Some states (e.g., New York) have well-structured public portals; others require FOIA-like requests for bulk data. We mitigate by (a) starting with the easy states for v1 coverage; (b) accepting that the long-tail of small insurers will have lower coverage; (c) using NAIC summary tables (published annually) as the sectoral aggregate constraint where per-entity detail is unavailable.

**Risk: Bermuda Monetary Authority disclosures are sparse for private entities.** Bermuda public registers cover publicly traded Bermuda companies and group financial reports of large groups, but the captive sub-entities used in many PE-affiliated structures may not be separately disclosed. We mitigate by (a) treating offshore captives as a single node per parent for v1; (b) using the U.S. cedent's Schedule S as the primary measurement of cession volume, since the offshore-side number must equal the U.S.-side number by Law 2.

**Risk: SEC Form NMFP changes format.** Has happened twice historically (2010 and 2016 restatement). We design the fetcher to be format-version-aware and to handle multiple historical schemas.

### 31. Methodological risks

**Risk: Maximum-entropy and minimum-density brackets are too wide for some arcs to be useful.** For sparsely connected sub-networks, the bracket can be 10x wide. We mitigate by (a) reporting the bracket explicitly rather than hiding it; (b) identifying which arcs have wide brackets and prioritizing direct-measurement acquisition for those (this drives the data-source roadmap); (c) accepting that some arcs are intrinsically less certain than others.

**Risk: Eisenberg-Noe assumes proportional payment under default; reality may have priority rules.** Funding agreements in insurer general accounts are senior to most other claims. Repo collateral is segregated. Reinsurance receivables have specific priority. We mitigate by extending the clearing-vector framework to multi-seniority following Rogers-Veraart 2013 and Acemoglu-Ozdaglar-Tahbaz-Salehi 2015.

**Risk: Fire-sale price-impact parameters are uncertain.** Different empirical studies report different price-impact elasticities for the same asset class. We mitigate by (a) reporting cascade outputs with a range of price-impact parameters; (b) calibrating to the three historical episodes such that the calibrated parameters reproduce the observed price moves.

**Risk: The model misses an important arc class.** Synthetic securitization (synthetic CDO, total-return swap structures) is a known underdocumented channel. CDS-style contingent claims (Banerjee-Feinstein 2019) are partially covered but not exhaustively. We mitigate by (a) explicitly enumerating known omissions in the methodology paper; (b) committing to ongoing updates as new instruments emerge.

### 32. Validation risks

**Risk: The model fails one of the three historical retrodictions.** This is a possibility we explicitly plan for. If the model fails a retrodiction, that is *information*: it means our cascade rules or runnability classification is wrong somewhere. We re-parameterize and re-validate. If the model fails after multiple re-parameterization attempts, we document why and either (a) restrict the published claims to areas where validation passes, or (b) re-scope the model.

**Risk: The model passes the historical retrodictions but extrapolates wildly off-baseline.** The 2007, 2008, and 2020 episodes all involved specific patterns; a model calibrated to those could be wrong about novel patterns. We mitigate by (a) reporting sensitivity to parameters explicitly; (b) running prospective scenarios that *don't* resemble the validation cases to check for behavior; (c) being honest in the published work about validation scope.

### 33. Regulatory and reputational risks

**Risk: Regulators object that the published work reveals information that should be confidential.** Our data is all from public sources, so this risk is bounded. We brief regulators in advance (§28) to ensure no surprises.

**Risk: Industry participants object that the analysis is unfair or alarmist.** We mitigate by (a) maintaining methodological neutrality — we report what the network looks like, not whether it's "good" or "bad"; (b) inviting industry comment in the review phase; (c) being scrupulous about data quality flags so claims are appropriately hedged.

**Risk: The framing is misread as predicting imminent crisis.** The breaking-point analysis quantifies *capacity* not *probability*. A breaking point of $X means the network can absorb shocks below $X without breaking; it does not mean a shock of $X will occur next quarter. We mitigate by clear communication and by reporting *capacity* and *historical occurrence rates of shocks* separately so users can form their own probability assessments.

### 34. Scope-creep risks

**Risk: The project tries to model every nonbank financial intermediary and bogs down.** We discipline scope by anchoring on the U.S. life insurance regulatory-arbitrage network as the core. Adjacent sectors (P&C insurers, hedge funds, REITs, pensions) are *contextual* — they appear as nodes when they hold or issue claims that enter the core network, but they are not modeled at entity granularity. Foreign insurers similarly appear only where they participate in the network.

**Risk: The visualization product becomes more ambitious than the analytical core.** We mitigate by treating the dataset as the primary deliverable. The visualization is built on top of the dataset; if visualization complexity threatens the analytical core, the visualization gets simplified, not the analysis.

---

## Part X — Timeline, milestones, and dependencies

### 35. The full timeline

This is a multi-year, full-throttle project. The user's instruction is "Big Bang" — deliver the whole thing — but no realistic engineering can produce a 100GB validated dataset, a 60-page methodology paper, a peer-reviewed publication, and an interactive web product in less than the time it takes to do each step properly. The schedule below is *aggressive* but *physically possible* with focused effort.

**Phase 1 — Foundation (months 1–6).**
- Finalize methodology document (this plan, plus appendices)
- Build base fetcher infrastructure (claimweb.fetchers)
- Acquire data for a single reference quarter (say, 2024-Q4) end-to-end
- Build network reconstruction for the reference quarter
- Verify Laws 1–4 hold on the reference quarter
- Initial Sankey visualization for the reference quarter

**Phase 2 — Historical reconstruction (months 7–12).**
- Extend fetchers backward to 2000-Q1
- Solve the network at each quarterly period
- Build the cascade simulator (Eisenberg-Noe + fire-sale + multi-constraint)
- Run baseline cascade scenarios for each period
- First historical-retrodiction attempts (2007 XFABS, 2008 AIG, 2020 stress)

**Phase 3 — Validation and methodology refinement (months 13–18).**
- Iterate on retrodictions until all three pass
- Build the visualization layer (Sankey + node-link + cascade-DAG)
- Build the interactive web product MVP
- Draft the methodology paper

**Phase 4 — External review and refinement (months 19–24).**
- Pre-submission review by three external experts
- Address review comments
- Industry and regulator briefings
- Submit to first-choice journal

**Phase 5 — Publication and launch (months 25–30).**
- Peer-review rounds
- Web product polish
- Press launch
- Open-source release
- Conference presentations (NBER Summer Institute, Jackson Hole-equivalent venues)

Total: approximately 2.5 years from start to peer-reviewed publication and public release.

### 36. Critical-path dependencies

The schedule has hard dependencies that must complete in order:
- Fetcher infrastructure → reference quarter solve → constraint system → cascade simulator → validation → paper
- Within data acquisition, NAIC Schedule S parsing is the longest pole (no central source, requires per-state work)
- Within methodology, the minimum-density solver is the hardest to implement correctly (the published reference implementations have known edge-case issues; we will need to fix them)

### 37. Resource requirements

The minimum viable team:
- One quantitative methodologist (responsible for the formal model, the solver, the cascade analysis)
- One data engineer (responsible for the fetchers and the normalization pipeline)
- One financial expert (responsible for the institutional knowledge — knowing what FABS is, why FHLB advances are classified as operating leverage, what a recapture trigger looks like in a Bermuda treaty)
- One visualization engineer (responsible for the Sankey, the web product, the cascade-DAG renderer)

The optimal team adds:
- A second quantitative methodologist for cross-checking the model
- A research assistant for literature management and citation tracking
- A regulatory affairs lead for the engagement work in §28

Hardware: Tesla's existing workstation handles the compute; nothing exotic is needed.

Software: Free and open-source for everything. Optional commercial: a Gurobi license for very-large-scale optimization if needed. SEC EDGAR, NAIC filings, FHLB reports, Z.1 — all free.

External relationships: Pre-existing relationships with FRB Foley-Fisher / Verani group would accelerate the validation step. Pre-existing relationship with one of the LISCC bank CROs would help with bank-side data interpretation.

---

## Part XI — The complete deliverable inventory

At full delivery, the project produces:

### Code
- `claimweb` Python package: ~15,000 lines of code, MIT-licensed, public GitHub repository
- ~30 fetcher modules covering all data sources
- ~5 algorithm modules covering reconstruction, cascade, multiplier, DebtRank, validation
- ~10 visualization modules covering all rendering needs
- ~3000 lines of test code, 95%+ coverage
- Docker container with pinned dependencies for full reproducibility

### Data
- Solved network panel: 2000-Q1 through current quarter, quarterly cadence, ~100GB compressed Parquet
- Cascade simulation database: ~1000 scenarios × 100 quarters, ~50GB Parquet
- Raw data archive: all source filings as acquired, ~500GB
- Data quality reports per period

### Documents
- Methodology paper: ~60–80 pages, peer-reviewed, published in top-5 finance journal
- Technical handbook: ~100 pages for analysts and developers
- User-facing summary report: ~20 pages for policymakers and press
- Data dictionary: ~50 pages, structured Markdown
- Three historical-episode validation reports: ~20 pages each
- This project plan and the precursor REGULATORY_ARBITRAGE.md as project memory

### Web product
- Interactive Sankey + node-link visualization
- Historical playback across 2000-Q1 through current
- Custom shock scenario builder
- Drill-down from sector to legal entity
- Downloadable subsets
- Embed-able views for press

### Engagement
- Briefings to FRB, OFR, FIO, NAIC, FSB
- Three external expert reviews
- Conference presentations at NBER, AEA, Western Finance Association, American Finance Association
- Press coverage in major financial outlets

---

## Part XII — The agent-based modeling layer (parallel to the analytical model)

### 38. Why ABM alongside Eisenberg-Noe

The clearing-vector framework gives a *static equilibrium* answer to "given a shock, what is the cleared payment vector?" That is precise, fast to compute, and analytically defensible. It misses two things the historical record shows matter:

1. **Intra-period sequencing.** In 2020, dealer banks pulled back from repo intermediation *before* MMF redemptions peaked; the order of events shaped which entities got the most stress. Clearing-vector solutions are order-independent by construction.
2. **Endogenous behavior change.** When stress arrives, agents change strategy (insurers draw down committed credit lines, banks tighten haircuts, MMFs shift to government-only holdings). The Liu-Paddrik-Yang-Zhang (2020) work on endogenously formed networks shows the network *structure itself* changes under stress, not just the arc weights on a fixed structure.

The agent-based model fills this gap. It is a *complement*, not a substitute, for the clearing-vector analysis. The clearing vector is the analytical backbone; the ABM is the operational simulator that captures dynamics.

### 39. The CLAIM-WEB agent-based architecture

Building on Bookstaber-Paddrik-Tivnan (2018) and adapted for the life-insurance-arbitrage network:

**Agent classes** (one per node class from §3):
- `SaverAgent` (M1, M2): consumption needs trigger redemption demand
- `BankTreasuryAgent` (M3, I4): LCR-targeting; manages HQLA portfolio
- `MMFAgent` (I1): Rule 2a-7 compliance; investor redemption response
- `SPVAgent` (I2): passthrough — no autonomous behavior
- `FHLBAgent` (I3): advance pricing based on demand and member creditworthiness
- `DealerAgent` (I4): repo intermediation; haircut-setting; balance-sheet capacity
- `CustodianAgent` (I5): sec-lending program management
- `AAMAgent` (I6, I7): asset allocation across affiliates; CLO management
- `BDCAgent` (I8): dividend management; line-of-credit drawing
- `InsurerAgent` (T1): liquidity management; surrender experience; hedging
- `ReinsurerAgent` (T2): claim payment; recapture risk
- `BorrowerAgent` (T3): default; covenant breach

Each agent class has a `decision_rule` method that, given the agent's state (balance sheet, regulatory ratios, market conditions) and the period's events, returns the agent's actions (transactions, redemptions, hedging trades).

**Decision rules.** Each agent class's decision rules are parameterized from the relevant literature:
- LCR-targeting from Greenwood-Landier-Thesmar (2015)
- MMF investor redemption response from Schmidt-Timmermann-Wermers (2016) and Cipriani-La Spada-Mulder (2023)
- Dealer haircut-setting from the Brunnermeier-Pedersen (2009) margin-spiral framework
- VA hedging program response from Sen (2023)
- Insurer surrender experience from policyholder-behavior actuarial models (calibrated from publicly disclosed lapse studies)

**Event-driven simulation.** Each simulation period (day or week, depending on configuration) processes:
1. Exogenous shocks (specified by the scenario)
2. Each agent observes the new state
3. Each agent computes its actions via its decision rule
4. Actions are executed in priority order; conflicts resolved by market-clearing
5. Balance sheets updated; conservation laws enforced (this is the integration with the analytical layer — any ABM output that violates conservation is a bug)
6. New state propagated; next period begins

The ABM runs over a configurable time horizon (typical: 90 days at daily granularity for crisis scenarios; 4 quarters at weekly granularity for slow-burn scenarios).

### 40. ABM-analytical integration

The ABM and clearing-vector models share the same underlying network structure (the solved network from Phase E). They differ in dynamics:
- The clearing vector computes the *terminal-state* equilibrium
- The ABM computes the *trajectory* to that equilibrium (or to a different equilibrium, if path-dependence matters)

For any scenario, both are run; the results compared. Three patterns emerge from the comparison:
- *Convergent*: ABM trajectory ends at the clearing-vector equilibrium. Confirms the clearing-vector framework is sufficient.
- *Path-dependent*: ABM trajectory ends at a different equilibrium depending on intra-period ordering. Indicates the clearing-vector understates uncertainty; report both equilibria.
- *Non-convergent*: ABM does not converge in the simulation horizon. Indicates the system is in an unstable region; this is itself an output worth reporting.

The ABM also provides a *crisis-onset detection* capability that the clearing-vector model lacks: identifying which sequence of small events precipitates a cascade, vs. which large-but-isolated events the system can absorb.

### 41. ABM implementation

A separate Python package, `claimweb.abm`, with the following structure:

```
claimweb/abm/
├── agents/                 # one module per agent class
├── simulator.py            # event loop and state management
├── scenarios.py            # pre-defined crisis scenarios
├── calibration.py          # parameter fitting from historical data
├── visualizer.py           # trajectory visualization (animated)
└── validate.py             # ABM-vs-clearing-vector comparison
```

Approximately 5000 lines of code. The ABM uses the Mesa Python framework (mature, well-documented, designed for exactly this purpose) for agent management; custom code for the financial-network-specific logic.

Runtime: an ABM scenario with ~100 agents over 90 daily periods runs in ~30 seconds on a single core. Across ~1000 scenarios × 100 quarters of starting states: ~3 hours wall-clock, parallelizable trivially.

### 42. ABM validation

Same three historical episodes (§17) but evaluated for trajectory-fit, not just terminal-state-fit:
- 2007 XFABS run: the ABM should reproduce the run's *time profile* — slow start in July, acceleration in August, peak in September. Not just the $18B total.
- 2008 AIG sec-lending: the ABM should reproduce the *trigger sequence* — collateral-call escalation, ratings actions, federal intervention.
- 2020 COVID stress: the ABM should reproduce the *event ordering* — initial credit-market stress, dealer pullback, prime MMF redemptions, FHLB advance surge, eventual Fed intervention via the MMLF and PMCCF facilities.

---

## Part XIII — Relationship with the FSR Dashboard

### 43. How the two projects interact

The FSR Dashboard reproduces FSR-style pillar assessments from origin data. CLAIM-WEB measures the underlying network and its breaking point. They are different artifacts, but they share substantial common infrastructure and they inform each other.

**Shared fetcher layer.** Both projects need SEC XBRL, FRB Z.1, FHLB data, NAIC data. The fetchers in `claimweb/fetchers/` are refactored from (and forward-compatible with) the existing FSR Dashboard `fetchers/`. Specifically:
- `fetchers/fred.py` (FSR) → `claimweb/fetchers/fred.py` with extensions for Z.1 instrument-level tables
- `fetchers/sec.py` (FSR) → `claimweb/fetchers/sec_xbrl.py` with extensions for affiliate-disclosure parsing
- New: `claimweb/fetchers/naic_*.py`, `fhlb_*.py`, `bma_*.py`, `sec_nmfp.py`, etc.

The refactor is non-destructive: FSR Dashboard continues to use its current fetcher interfaces; CLAIM-WEB imports the same fetchers via a thin compatibility shim. No fork, no divergence.

**Shared origin-data discipline.** Both projects commit to using only free, primary, origin sources. Both flag data quality explicitly. Both publish methodology.

**Different outputs.** FSR Dashboard outputs are scored time series (Pillar 1 = X, Pillar 4 = Y). CLAIM-WEB outputs are network states, claim multipliers, and breaking-point thresholds. The two are not interchangeable.

**Feedback loop.** CLAIM-WEB outputs feed back into the FSR Dashboard's Pillar 4 indicators (the four-surface architecture in REGULATORY_ARBITRAGE.md becomes directly populated from CLAIM-WEB's solved network). FSR Dashboard's per-pillar growth-rate signals feed into CLAIM-WEB's regime classification (are we in normal times or stress?).

### 44. Repository organization

Two separate GitHub repositories, with a shared dependency:
- `fsr-dashboard`: existing repository, continues current scope
- `claimweb`: new repository
- `fsr-shared-fetchers`: extracted shared fetcher package, both repos depend on it

This is the standard pattern for related-but-distinct projects sharing a common data layer. Each repo has its own release cycle, its own contributor base, its own documentation, and its own user community.

### 45. Sequencing relative to FSR Dashboard

FSR Dashboard remains the operational priority. The FSR Dashboard's audit closure and gap remediation continues on its current schedule. CLAIM-WEB kicks off in parallel with explicit checkpoints:

- **Month 0 (now):** project plan finalized (this document)
- **Month 1:** repository created, basic infrastructure scaffolded
- **Months 1–3:** the shared-fetcher refactor proceeds in parallel with FSR Dashboard work; FSR Dashboard remains the priority for the project owner's time
- **Months 4–6:** CLAIM-WEB Phase 1 work begins in earnest; FSR Dashboard moves to maintenance mode

The plan does not require pausing the FSR Dashboard work. The two run in parallel with periodic synchronization at the shared-fetcher interface.

---

## Part XIV — Data governance, reproducibility, and provenance

### 46. Reproducibility regime

The project commits to *bit-level reproducibility*: any user with the published code and the published raw-data archive can reproduce every figure, every table, every number in the methodology paper. This is a hard requirement for top-tier journal submissions (JF and RFS both require reproducibility packages) and a hard requirement for the project's credibility with regulators.

**The reproducibility package** consists of:
- The full `claimweb` Python package with pinned dependency versions
- A Docker container with the entire computational environment
- The raw-data archive (or pointers to permanent archive locations, e.g. Zenodo)
- A `make all` target that runs the full pipeline from raw data through every published figure
- A `verify.py` script that checks every published number against re-computed values

The reproducibility check runs in CI on every code change. If `verify.py` fails, the change is blocked.

### 47. Data versioning

Raw data is content-addressed (SHA-256 hash) and stored immutably. Each fetcher records the hash of every acquired raw data file. The solved network for a given period is versioned as `network/{period}/v{N}/`, where `v1` is the first solved version and subsequent versions reflect methodology changes (with full changelog).

This ensures that any output can be traced to (a) the exact code that produced it, (b) the exact raw data inputs, (c) the exact methodology configuration. Reviewers and replicators get this full chain of custody.

### 48. Methodology change governance

After the methodology paper's publication, the methodology is *frozen* in the form that was peer-reviewed. Subsequent changes follow a numbered amendment process:

- **Amendment A1, A2, ...**: substantive methodology changes (e.g., adding a new arc class, changing a cascade rule). Each amendment is documented in a public log, with rationale, before-and-after comparison, and a re-run of all historical validation episodes to confirm the amendment does not break retrodiction.
- **Patch P1, P2, ...**: non-substantive fixes (typos, bug fixes that change results within tolerance). Documented in a public changelog.

The published dataset at any point in time corresponds to a specific (methodology amendment, code version) tuple. Historical datasets are not silently rewritten.

### 49. Open-data licensing

The published dataset is released under the Open Data Commons Open Database License (ODbL) — the same license used by OpenStreetMap. This permits redistribution and derivative works while preserving attribution and the requirement that derivative datasets be made similarly available.

The code is released under MIT. The methodology paper is released under CC-BY-4.0 (compatible with most journal policies for accepted manuscripts).

### 50. Long-term data stewardship

The dataset must remain accessible for at least 10 years to support follow-on research. Stewardship arrangements:
- **Zenodo deposit** with DOI, permanent retention via CERN backing
- **University-partner institutional repository** as secondary archive
- **Software Heritage** for code preservation
- **Internet Archive Wayback Machine** snapshots of the interactive web product

The hosting cost over 10 years is modest (~$10K total) and is budgeted into the project.

---

## Part XV — Intellectual property, authorship, and project governance

### 51. Authorship architecture

The project's deliverables fall into categories with different authorship norms:

- **Software**: collective contribution; all contributors credited in CITATION.cff. No "first author" of the code.
- **The methodology paper**: traditional academic authorship by the methodologist(s), data engineer, and financial expert. Author order to be agreed upon in advance.
- **The dataset**: cited via DOI; no individual authors, but a release-notes file credits all contributors.
- **The web product**: collectively credited on the site's About page.

### 52. Decision-making authority

The project owner retains technical and strategic authority. Decisions are made by the project owner after Claude provides analysis, options, and recommendations.

Specific decision categories:
- **Scope decisions** (what is in, what is out): project owner
- **Methodology decisions** (which estimator, which cascade rule): collaborative analysis, project owner decides
- **Publication decisions** (where to submit, when to release): project owner
- **Partnership decisions** (which institutions to brief, which co-authors to invite): project owner

### 53. Funding and resource model

The project is unfunded internally (no grant agency) but operates on the same model as the FSR Dashboard. If external funding becomes available (NSF, Sloan, Smith Richardson, OFR research grant) it is welcome but not relied upon. The work proceeds with internal resources regardless.

If a partnership with an academic institution emerges, the institution provides additional research-assistant capacity in exchange for co-authorship on the published paper.

### 54. Conflict-of-interest management

The project examines the financial activities of named entities (insurers, banks, asset managers). To preserve credibility:
- The project does not accept funding from any entity covered in its analysis
- Contributors disclose any equity holdings, advisory relationships, or other ties to covered entities
- Industry briefings (§28) are clearly distinguished from review or input — they are *informational*, not decision-influencing
- Press coverage is responded to factually; no exclusive arrangements with any outlet

---

## Part XVI — Applications and policy uses

### 55. Direct applications

Once delivered, the project's outputs serve at least the following uses:

**Macroprudential monitoring.** Regulators with mandate (FSOC, FSB, ESRB) can use the solved network panel and breaking-point thresholds as inputs to their own systemic risk assessments. The four-surface architecture maps directly to the FSB's proposed core metrics for nonbank-bank-insurer monitoring.

**Stress testing augmentation.** The FRB's CCAR/DFAST and the EIOPA insurance stress tests focus on direct exposures and single-entity solvency. CLAIM-WEB provides the network overlay that captures cross-entity, cross-instrument contagion that direct-exposure stress tests miss.

**Capital regulation evaluation.** Proposed changes to LCR HQLA composition, FHLB advance treatment, or offshore reinsurance recognition can be evaluated via CLAIM-WEB: simulate the network state under proposed and current rules; compare breaking-point thresholds.

**Academic research.** The dataset enables follow-on work on PE-affiliated insurer behavior, the Bermuda cession dynamic, the bank-insurer-MMF intermediation chain, the contagion properties of CLO-heavy portfolios, etc. We expect (and welcome) 10+ follow-on papers from other research groups within five years of release.

**Financial press and public understanding.** The interactive web product makes the network legible to non-specialists. The November 2025 Bloomberg piece on Athene-Apollo was effective journalism but relied on hand-assembled data. CLAIM-WEB provides the systematic, query-able underlying data layer.

**Industry risk management.** Reinsurers, rating agencies, and counterparties to PE-affiliated insurers can use CLAIM-WEB's network maps to assess their own exposures.

### 56. The policy-portfolio document

In addition to the methodology paper, the project produces a separate **policy-portfolio document** approximately 40 pages targeting a regulator audience:
- Section 1: the framing (regulatory-arbitrage network, conservation-circuit model)
- Section 2: the empirical findings (claim multipliers, breaking points)
- Section 3: policy levers that change the network's properties (LCR amendment, FHLB advance reclassification, offshore-cession consolidation, etc.)
- Section 4: counterfactual analysis (what would the network look like under each proposed reform?)
- Section 5: monitoring framework recommendations

This document is released alongside the methodology paper but is targeted at the policy audience and written in plain English. It explicitly does *not* advocate specific reforms — it presents the network's behavior under alternatives and lets policymakers choose.

### 57. The historical-counterfactuals report

A supplementary report uses the model to ask: had the network been different in 2007 / 2008 / 2020, would the historical episodes have unfolded differently? Counterfactuals:
- **2007 counterfactual:** had FABS been classified as debt (not HQLA-eligible) since 2003, what would the network state in 2007 have been? Would the run have occurred?
- **2008 counterfactual:** had AIG's sec-lending program been subject to a hard collateral cap, would the federal bailout have been required?
- **2020 counterfactual:** had FHLB advance availability to insurers been constrained, would the March 2020 stress have transmitted differently?

These are not predictions but illustrations. They show the model's behavior under counterfactual conditions; they let readers evaluate the model's plausibility against their own intuitions about what would have happened.

---

## Part XVII — Long-run roadmap (beyond v1)

### 58. After the initial publication

The project does not end with v1 publication. The dataset and tools are maintained and extended:

**Year 3–5 expansions:**
- **Extension to P&C and reinsurance.** The P&C insurance sector has its own network structure (reinsurance, catastrophe bonds, etc.) that interacts with the life network. Extend the node and arc taxonomies to cover P&C.
- **Extension to pension funds.** Defined-benefit pension funds hold large life-insurer products (group annuities, pension risk transfer). Extend the network to include pension funds as a node class with their specific runnability profile.
- **Extension to foreign life insurers and cross-border arcs.** Connect the U.S. network to the European (Solvency II) and U.K. (PRA) life insurance networks.

**Year 5–10 extensions:**
- **Tokenized money market funds and stablecoins.** McCabe (2024, "A Framework for Understanding the Vulnerabilities of New Money-Like Products," FRB FEDS Notes) frames these as a new arc class that may eventually become significant. The taxonomy is extensible to capture them.
- **Central counterparty cleared instruments.** Repo is moving toward central clearing; CLAIM-WEB should accommodate the CCP node class.
- **Climate-related contingent claims.** As climate-disclosure rules mature, climate-contingent arcs (parametric climate insurance, climate-related sovereign bond clauses) become measurable and should be added.

### 59. Ongoing operational tempo

After v1, the dataset refreshes quarterly with each Z.1 release and SEC quarterly filings. The web product updates automatically. The methodology paper does not change after publication; amendments are documented separately per §48.

A quarterly *State of the Web* note (approximately 10 pages) is published alongside each dataset refresh, summarizing what changed in the network during the quarter, which entities moved most, and any notable shifts in claim multipliers or breaking-point thresholds. The notes are not journal articles but are public, time-stamped commentary.

### 60. Termination criteria

The project terminates (transitions to archive-only) under any of:
- The dataset and tools are subsumed by a regulator's official public publication (e.g., the OFR begins publishing equivalent network reconstructions; in that case CLAIM-WEB has succeeded in its mission and gracefully retires)
- The underlying data sources become unavailable in a way that cannot be recovered (e.g., the SEC discontinues XBRL filings)
- The project owner determines that the marginal value of continued maintenance is below the cost

At termination, the final dataset and all code are deposited in permanent archives (§50). The web product is converted to a static archive of the most recent state.

---

## Conclusion

This is the project framed against your instruction. The conservation-circuit framing makes the network computable from partial data via well-established techniques (Eisenberg-Noe clearing, Anand-Craig-von Peter bracketing, Cont-Schaanning fire-sale extension, Banerjee-Feinstein contingent payments, Battiston DebtRank, Bookstaber-Paddrik-Tivnan agent-based simulation). The historical episodes (2007 XFABS, 2008 AIG, 2020 COVID) provide validation targets at both terminal-equilibrium granularity (clearing-vector model) and trajectory granularity (ABM). The data sources are all free and origin-grade. The methodology is bounded by published literature with established peer-review standing. The deliverable scope produces an artifact that contributes to academic, regulatory, and public understanding.

The work is large but it is not speculative. Every step has a precedent in the literature; the contribution is the specific application and the specific dataset, not the underlying mathematics. The two-and-a-half year timeline assumes focused effort and is approximately what the published Anand-Craig-von Peter and Bookstaber-Paddrik-Tivnan lines of work have typically taken from initial implementation through journal publication.

The goal you stated — quantify the web and the breaking point — has a definite operational meaning in this plan:
- **The web** is the solved from-whom-to-whom matrix $\hat{X}(t)$ across all instruments and all entities, quarterly from 2000-Q1 through current. Its size is the claim multiplier $M(t)$. Its ownership structure is G3. Its supervisory coverage is G2. Its breaking properties are computed from G1.
- **The breaking point** is the smallest shock magnitude $\theta^*(s, k)$ at any chosen entry node $s$ and instrument $k$ that triggers a cascade resulting in real-dollar shortfall. Computed via the Eisenberg-Noe + fire-sale + multi-constraint + contingent-payment framework. Cross-validated by agent-based simulation. Reported with explicit uncertainty bands from the maximum-entropy / minimum-density bracketing.

Both are reported quarterly across 2000–present, validated against the three crisis episodes, with explicit uncertainty bands. Both are made accessible to academic, regulatory, and public audiences via published methodology, downloadable dataset, and interactive web product.

The conservation laws make this tractable. Without them, this would be data-collection work with no closure. With them, it is a constrained inference problem with proven mathematical structure.

### The no-compromise commitment

Per the directive: no versioning, no cutting corners, no laziness. Concretely:

- **Both maximum-entropy and minimum-density reconstruction are computed.** Not one or the other for v1. Both, with the bracket reported on every arc.
- **Both clearing-vector and agent-based simulations are run.** Not one as a primary and the other as future work. Both, with comparison reported.
- **All three historical episodes validate the model.** Not one as a pilot. All three, with full trajectory comparison.
- **The full panel from 2000-Q1 through current quarter is reconstructed.** Not a recent-only proof of concept. The full 25-year panel.
- **All data sources are origin-grade and free.** No paid aggregator dependencies anywhere in the pipeline. NAIC PDFs parsed; Bermuda registers downloaded; SEC EDGAR mined; FRB Z.1 ingested. The discipline that drives the FSR Dashboard carries forward.
- **The methodology paper targets a top-5 finance journal.** Not a working paper. A *Journal of Finance* / *Review of Financial Studies* / *Journal of Financial Economics* / *Management Science* / *Quantitative Finance* submission with reproducibility package.
- **The dataset is permanently archived.** Not a hosted website that may disappear. Zenodo DOI, institutional backup, Software Heritage code preservation.
- **The conclusions extend to all policy implications honestly.** Not a politically convenient subset. The policy-portfolio document covers every lever that changes the network's properties, including levers that some constituencies will dislike.

### First-week actions

To make the project concrete from day one, the first week's work:

1. **Create the GitHub repository** `claimweb` with the directory skeleton from §18.
2. **Set up the development environment**: pyproject.toml with pinned dependencies, pytest scaffolding, Docker file, pre-commit hooks, CI configuration.
3. **Implement the first fetcher**: `claimweb.fetchers.fhlb_combined`. The FHLB Office of Finance Combined Financial Report is the easiest data source (structured PDFs, clear quarterly cadence, single download URL). Successfully ingest the 2024-Q4 report end-to-end; emit normalized records.
4. **Build the conservation-law checker**: `claimweb.constraints.kcl` with property-based tests. The balance-sheet identity check on any node, given its arcs, must run in <1ms and report violation with full diagnostic.
5. **Draft the reference-quarter (2024-Q4) network-state target document**: what the solved network for 2024-Q4 should look like at the end of Phase 1, against which all subsequent work is measured.

The first deliverable (end of week 4) is a successful end-to-end reconstruction of a *single arc* of the 2024-Q4 network — say, FHLB advances to U.S. life insurer members — with full provenance, conservation-law checking, and uncertainty quantification. That single arc, done end-to-end, validates the entire architecture. Everything afterward is replication and extension.

This is the project, at full throttle, with no compromises. The plan is ready to execute.

