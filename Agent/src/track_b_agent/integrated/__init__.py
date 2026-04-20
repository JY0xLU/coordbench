"""Integrated Track B runner that plugs into CoordBench.

This lives under Agent/ so all Track B “agent logic” stays in the Agent folder.
"""

from track_b_agent.integrated.pipeline import run_track_b

__all__ = ["run_track_b"]

