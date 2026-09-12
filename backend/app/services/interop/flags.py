import os

# Kill switch for the entire interoperability feature (P70: per-connector
# kill switch is separate — this is the whole-feature one, same pattern as
# ASK_BRAGI_ENABLED in app/services/ask_bragi/service.py). Default false:
# merging this code changes nothing for any real user until explicitly
# activated. Every `/admin/interop/*` route in app/main.py checks this
# first and every connector call path checks it again before making any
# outbound network request.
INTEROP_FHIR_ENABLED = os.getenv("INTEROP_FHIR_ENABLED", "").strip().lower() in {"1", "true", "yes"}

# Encryption key for InteropSecret.ciphertext (see crypto.py). Required only
# once a connection actually needs a secret (static bearer token, OAuth2
# client secret, SMART private key, ...) — a connection using auth_type
# "none" never touches this. Fails closed (raises) rather than storing
# plaintext if a secret write is attempted without this set.
INTEROP_SECRET_ENCRYPTION_KEY = os.getenv("INTEROP_SECRET_ENCRYPTION_KEY", "").strip()

ENVIRONMENT = os.getenv("ENVIRONMENT", "production").lower()
IS_PRODUCTION = ENVIRONMENT == "production"
