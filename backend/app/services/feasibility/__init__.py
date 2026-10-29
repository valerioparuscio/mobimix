"""Step 8 - rule-based feasibility (FeasibilityChecker). Runs BEFORE any ranking:
a portfolio that cannot serve the household needs is rejected with a reason."""

from .checker import RuleBasedFeasibilityChecker

__all__ = ["RuleBasedFeasibilityChecker"]
