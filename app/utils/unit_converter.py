import re
from typing import Tuple

# Unit categories and their relative factors to the base unit
UNIT_CATEGORIES = {
    "weight": {
        "base": "kg",
        "aliases": {
            "kg": "kg",
            "kgs": "kg",
            "kilogram": "kg",
            "kilograms": "kg",
            "ton": "ton",
            "tons": "ton",
            "mt": "ton",
            "metric_ton": "ton",
            "metric_tons": "ton",
            "bag": "bag",
            "bags": "bag",
            "crate": "crate",
            "crates": "crate",
        },
        "factors": {
            "kg": 1.0,
            "ton": 1000.0,
            "bag": 50.0,  # Standard grain bag in Ghana is ~50kg
            "crate": 25.0,  # Standard tomato/vegetable crate is ~25kg
        },
    },
    "volume": {
        "base": "liter",
        "aliases": {
            "l": "liter",
            "liter": "liter",
            "liters": "liter",
            "litre": "liter",
            "litres": "liter",
            "gallon": "gallon",
            "gallons": "gallon",
            "gal": "gallon",
        },
        "factors": {
            "liter": 1.0,
            "gallon": 4.5,  # Imperial gallon commonly used in Ghana (~4.5L)
        },
    },
    "countable": {
        "base": "piece",
        "aliases": {
            "piece": "piece",
            "pieces": "piece",
            "pcs": "piece",
            "pc": "piece",
            "unit": "piece",
            "units": "piece",
            "bundle": "bundle",
            "bundles": "bundle",
            "bdl": "bundle",
        },
        "factors": {
            "piece": 1.0,
            "bundle": 10.0,  # Default bundle size (e.g. tubers/herbs)
        },
    },
}


def normalize_unit_name(unit: str) -> str:
    """Standardizes whitespace, cases, and spelling variations of unit names."""
    if not unit:
        return ""
    normalized = unit.strip().lower()
    normalized = re.sub(r"[^a-z0-9_]", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def get_unit_category_and_standard_name(unit_name: str) -> Tuple[str, str]:
    """Finds the category and canonical name for a given unit. Raises ValueError if unknown."""
    norm = normalize_unit_name(unit_name)
    for category, cat_data in UNIT_CATEGORIES.items():
        if norm in cat_data["aliases"]:
            return category, cat_data["aliases"][norm]
    raise ValueError(f"Unknown or unsupported unit: {unit_name}")


def convert_quantity(quantity: float, from_unit: str, to_unit: str) -> float:
    """
    Converts quantity from one unit to another.
    Raises ValueError if conversion is impossible (e.g. weight to volume, or unknown unit).
    """
    from_norm = normalize_unit_name(from_unit)
    to_norm = normalize_unit_name(to_unit)

    if from_norm == to_norm:
        return quantity

    from_cat, from_std = get_unit_category_and_standard_name(from_unit)
    to_cat, to_std = get_unit_category_and_standard_name(to_unit)

    if from_cat != to_cat:
        raise ValueError(
            f"Incompatible unit categories: cannot convert from {from_unit} ({from_cat}) to {to_unit} ({to_cat})"
        )

    # Convert from source unit to category base unit, then to target unit
    cat_data = UNIT_CATEGORIES[from_cat]
    base_qty = quantity * cat_data["factors"][from_std]
    target_qty = base_qty / cat_data["factors"][to_std]

    return target_qty
