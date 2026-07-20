"""Python plugin rules (checks that need document structure, not attributes)."""

from physcheck.engine.plugins import l0_structure, l1_cross, l2_map, l2_solar_geo

#: id -> (layer, severity, title, citation) for all builtin plugin rules.
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    **l0_structure.PLUGIN_RULES,
    **l1_cross.PLUGIN_RULES,
    **l2_map.PLUGIN_RULES,
    **l2_solar_geo.PLUGIN_RULES,
}

__all__ = ["PLUGIN_RULES"]
