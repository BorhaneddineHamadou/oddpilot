"""Python plugin rules (checks that need document structure, not attributes)."""

from physcheck.engine.plugins import (
    l0_structure,
    l1_cross,
    l2_map,
    l2_solar_geo,
    l3_kinematics,
    l4_storyboard,
    l5_odd,
    l6_statistical,
)

#: id -> (layer, severity, title, citation) for all builtin plugin rules.
PLUGIN_RULES: dict[str, tuple[str, str, str, str]] = {
    **l0_structure.PLUGIN_RULES,
    **l1_cross.PLUGIN_RULES,
    **l2_map.PLUGIN_RULES,
    **l2_solar_geo.PLUGIN_RULES,
    **l3_kinematics.PLUGIN_RULES,
    **l4_storyboard.PLUGIN_RULES,
    **l5_odd.PLUGIN_RULES,
    **l6_statistical.PLUGIN_RULES,
}

__all__ = ["PLUGIN_RULES"]
