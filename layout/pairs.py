"""Pure lower/upper pair logic shared by corrections and delivery."""
from layout.values import MISSING

QUALIFIED = 'qualified'
INVERTED = 'inverted'
MISSING_STATE = 'missing'


def pair_fields(layout):
    """Return the (lower, upper) FieldSpec pair, or None for layouts without one."""
    if layout.calibration_pair is None:
        return None
    names = {field.name: field for field in layout.fields}
    lower_name, upper_name = layout.calibration_pair
    return names[lower_name], names[upper_name]


def classify_pair(lower_value, upper_value):
    if lower_value is MISSING or upper_value is MISSING:
        return MISSING_STATE
    if lower_value > upper_value:
        return INVERTED
    return QUALIFIED
