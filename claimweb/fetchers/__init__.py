"""Primary-source data fetchers (project plan §10, §11).

One module per data source. Every fetcher conforms to the ``BaseFetcher``
contract: ``acquire`` (raw bytes), ``parse`` (normalized facts),
``validate`` (per-fetcher invariant checks). All emit ``ArcFact`` rows
with a ``DataQualityFlag`` per CLAUDE.md standing rule.

Planned modules
---------------
- ``base``              ``BaseFetcher`` abstraction + ``ArcFact`` schema
- ``fhlb_combined``     FHLB Office of Finance Combined Financial Report (§10.4)
- ``z1``                FRB Z.1 quarterly release: L.116, L.121, L.207, L.208,
                        L.211, L.226, L.227 (§10.1)
- ``sec_xbrl``          SEC companyfacts XBRL for LIFE_INSURERS panel (§10.2)
- ``sec_nmfp``          SEC Form NMFP money-market fund holdings (§10.5)
- ``sec_adv``           SEC Form ADV investment-adviser registrations (§10.6)
- ``sec_13f``           SEC Form 13F institutional holdings
- ``sec_focus``         SEC Form FOCUS broker-dealer financial reports
- ``naic_schedule_s``   NAIC Schedule S reinsurance cessions (§10.3)
- ``naic_schedule_d``   NAIC Schedule D security-by-security holdings
- ``naic_schedule_ba``  NAIC Schedule BA alternative assets
- ``naic_schedule_db``  NAIC Schedule DB derivatives
- ``frb_efa_fabs``      FRB Enhanced Financial Accounts FABS daily (§10.9)
- ``ffiec_y9c``         FFIEC Y-9C bank holding-company financial reports
- ``fio_annual``        Federal Insurance Office Annual Report data
- ``ofr``               Office of Financial Research public datasets
- ``bma_register``      Bermuda Monetary Authority registers
- ``treasury_tic``      Treasury TIC reports
"""
