"""Shared contract, testbench and planner for every simulator in this repo.

`common` never imports from an approach directory. Approaches import from here
and expose their models through `common.simulator.Simulator`. Keeping the
dependency one-way is what lets a new approach be added without touching any
existing one.
"""
