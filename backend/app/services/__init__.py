"""Business logic, one sub-package per pipeline stage (see `interfaces.py`).

Services never import from `app.api` and know nothing about the UI, so MobiMix City can
later call the same analysis repeatedly on synthetic households.
"""
