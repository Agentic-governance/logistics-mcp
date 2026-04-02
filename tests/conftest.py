"""Pytest configuration for SCRI Platform tests."""
import sys
import os

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "slow: marks tests as slow (call external APIs)")
    config.addinivalue_line("markers", "network: requires external network access")


def pytest_collection_modifyitems(config, items):
    """Skip network-dependent tests by default."""
    skip_network = pytest.mark.skip(reason="requires network")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
