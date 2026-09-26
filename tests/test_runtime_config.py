from __future__ import annotations

from scripts.runtime_config import model_profile_inventory, resolve_config_view


def test_native_view_applies_legacy_then_canonical_blocks() -> None:
    # Given shared, legacy native, and canonical native settings.
    config = {
        "categories": {
            "search": {
                "models": ["shared/first", "shared/second"],
                "reasoning": "low",
            }
        },
        "[senpi]": {
            "categories": {
                "search": {
                    "models": ["legacy/first", "legacy/second"],
                    "reasoning": "high",
                }
            }
        },
        "[native]": {
            "categories": {
                "search": {
                    "reasoning": "max",
                }
            }
        },
        "[opencode]": {"categories": {"search": {"model": "inactive/model"}}},
    }

    # When the native view is resolved through the legacy alias.
    resolved = resolve_config_view(config, "senpi")

    # Then canonical native values win, ordered chains remain intact, and controls disappear.
    assert resolved == {
        "categories": {
            "search": {
                "models": ["legacy/first", "legacy/second"],
                "reasoning": "max",
            }
        }
    }


def test_selected_profile_layers_apply_after_native_base() -> None:
    # Given every native profile precedence layer with distinct values.
    config = {
        "task": {"winner": "shared", "shared": True},
        "[senpi]": {"task": {"winner": "legacy", "legacy": True}},
        "[native]": {"task": {"winner": "native", "native": True}},
        "profiles": {
            "focused": {
                "task": {"winner": "profile", "profile": True},
                "[senpi]": {
                    "task": {"winner": "profile-legacy", "profile_legacy": True}
                },
                "[native]": {
                    "task": {"winner": "profile-native", "profile_native": True}
                },
            }
        },
    }

    # When the selected native profile is resolved.
    resolved = resolve_config_view(config, "native", profile="focused")

    # Then all layers contribute and the profile-native layer wins.
    assert resolved == {
        "task": {
            "winner": "profile-native",
            "shared": True,
            "legacy": True,
            "native": True,
            "profile": True,
            "profile_legacy": True,
            "profile_native": True,
        }
    }


def test_missing_profile_falls_back_to_unprofiled_view() -> None:
    # Given a config with one profile.
    config = {
        "model_profile": "capable",
        "[native]": {"telemetry": {"enabled": False}},
        "profiles": {"focused": {"model_profile": "deep-work"}},
    }

    # When a different profile name is selected.
    resolved = resolve_config_view(config, "native", profile="missing")

    # Then the base and native view remain effective without inventing a profile.
    assert resolved == {
        "model_profile": "capable",
        "telemetry": {"enabled": False},
    }


def test_opencode_view_does_not_apply_native_blocks() -> None:
    # Given both harness blocks.
    config = {
        "agents": {"oracle": {"model": "shared/model"}},
        "[native]": {"agents": {"oracle": {"model": "native/model"}}},
        "[opencode]": {"agents": {"oracle": {"model": "opencode/model"}}},
    }

    # When the OpenCode view is resolved.
    resolved = resolve_config_view(config, "opencode")

    # Then only the OpenCode harness block is active.
    assert resolved == {"agents": {"oracle": {"model": "opencode/model"}}}


def test_model_profile_inventory_reports_explicit_selection_only() -> None:
    # Given custom profile definitions without an active main-session selection.
    config = {
        "model_profiles": {
            "house": {"models": ["exampleprovider/primary"]},
            "night": {"models": ["exampleprovider/secondary"]},
        },
        "[native]": {"telemetry": {"enabled": False}},
    }

    # When main-session profile inventory is requested.
    inventory = model_profile_inventory(config, "native")

    # Then configured choices are listed without fabricating a default selection.
    assert inventory == {
        "active": None,
        "configured": ["house", "night"],
    }
