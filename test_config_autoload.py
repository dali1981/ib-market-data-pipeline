"""Test that config auto-loads correctly."""

from dlt_ibapi.config_loader import get_connection_config, get_historical_config

# Test auto-loading
print("Testing config auto-load...")
print()

conn_config = get_connection_config()
print(f"Connection Config (auto-loaded):")
print(f"  Host: {conn_config.host}")
print(f"  Port: {conn_config.port}")
print(f"  Client ID: {conn_config.client_id}")
print(f"  Ready Timeout: {conn_config.ready_timeout}")
print()

hist_config = get_historical_config()
print(f"Historical Config (auto-loaded):")
print(f"  Duration: {hist_config.duration}")
print(f"  Bar Size: {hist_config.bar_size}")
print(f"  What to Show: {hist_config.what_to_show}")
print(f"  Use RTH: {hist_config.use_rth}")
print(f"  Timeout: {hist_config.timeout}")
print()

print("✓ Config auto-load working!")
print()
print("Expected values from default config:")
print("  Port: 4002 (IB Gateway Paper Trading)")
print("  Bar Size: 1 min")
print("  Duration: 1 D")
