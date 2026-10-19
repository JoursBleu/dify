"""Model IDs that must never be packaged; shared by the generator and package check."""

EXCLUDED_MODELS = frozenset({
    "MiniCPM5-2B", "MiniCPM-V-4.7-1B", "MiniCPM-V-4.7-35B-A3B",
    "DeepSeek-V4-Flash-Vision-Exp",
})
