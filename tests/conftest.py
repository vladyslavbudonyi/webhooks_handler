import os

# conftest.py is imported before any test module, so this runs before `app.config` builds
# `settings` at import time. Env vars take precedence over .env in pydantic-settings, so a
# developer's local API_SECRET_ARN can never trigger a real Secrets Manager call from pytest.
os.environ["API_SECRET_ARN"] = ""
