"""Fire-sale indirect contagion
(Cifuentes-Ferrucci-Shin 2005; Cont-Schaanning 2017; project plan §15).

Augments the Eisenberg-Noe clearing vector with price-impact dynamics:
when a node must liquidate illiquid assets to meet redemptions, the
liquidation moves prices, marking everyone's portfolio down, forcing
further liquidations.

Parameterized by an asset-specific price-impact function calibrated from
empirical liquidity (Pavlova-Petrasek for corporate bonds;
Greenwood-Landier-Thesmar for the general framework). Critical for the
CLAIM-WEB setting because life-insurer general accounts hold illiquid
CLO mezzanine tranches and CRE loans whose fire-sale impact is the
dominant transmission channel.

Per ``cascade-author`` skill: fire-sale layers ON TOP of Eisenberg-Noe;
it does not replace the clearing computation, it iterates with it.

Planned public interface
------------------------
- ``clear_with_fire_sale(network, capacities, price_impact, *,
                         max_iter, tol) -> ClearingVectorWithFireSale``
"""
