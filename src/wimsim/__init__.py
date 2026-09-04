"""wim-sim -- Weigh-in-Motion self-calibration testbed."""

__version__ = "0.1.0"

# Bumped whenever an emitted event payload changes shape. Carried in every event and in every
# run manifest so old artifacts stay interpretable.
#
# 1.1.0 -- added the optional `traceparent` field to every payload (phase 4). Additive and
#          optional, so a consumer written against 1.0.0 keeps working unchanged.
SCHEMA_VERSION = "1.1.0"
