"""The weekly start/sit model (ADR-095).

A decision-layer model: it projects a player's **next game** as a distribution, from the
rest-of-season snapshot's point-in-time features plus the game's environment and opponent.
It may read sportsbook lines and it is read by no intrinsic model. See
:mod:`ffdraft.weekly.frozen` for the declared specification and promotion rule.
"""
