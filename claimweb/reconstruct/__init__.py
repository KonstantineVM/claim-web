"""Network reconstruction solvers (project plan §13 Phase C).

Two methods, both run, with the spread between them reported per-arc as
a structural-uncertainty bracket — following Anand-Craig-von Peter
(2015)'s explicit recommendation.

Modules
-------
- ``max_entropy``  Upper (2004) maximum-entropy / RAS / iterative
                   proportional fitting
- ``min_density``  Anand-Craig-von Peter (2015) minimum-density relaxation
- ``solver``       harness that runs both and brackets per-arc
- ``validate``     internal-consistency checks on the reconstructed network
"""
