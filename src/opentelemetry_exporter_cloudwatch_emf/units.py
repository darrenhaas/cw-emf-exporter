"""Unit mapping from OpenTelemetry to CloudWatch.

OpenTelemetry uses UCUM (Unified Code for Units of Measure).
CloudWatch uses its own unit names.
See: https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_MetricDatum.html
"""

from typing import Optional

OTEL_TO_CLOUDWATCH_UNITS: dict[str, str] = {
    # Time
    "s": "Seconds",
    "ms": "Milliseconds",
    "us": "Microseconds",
    "ns": "Microseconds",  # CloudWatch doesn't have nanoseconds
    # Bytes
    "By": "Bytes",
    "KiBy": "Kilobytes",
    "MiBy": "Megabytes",
    "GiBy": "Gigabytes",
    "TiBy": "Terabytes",
    "KBy": "Kilobytes",
    "MBy": "Megabytes",
    "GBy": "Gigabytes",
    "TBy": "Terabytes",
    # Bits
    "bit": "Bits",
    "Kibit": "Kilobits",
    "Mibit": "Megabits",
    "Gibit": "Gigabits",
    "Tibit": "Terabits",
    # Rates
    "By/s": "Bytes/Second",
    "KiBy/s": "Kilobytes/Second",
    "MiBy/s": "Megabytes/Second",
    "GiBy/s": "Gigabytes/Second",
    "TiBy/s": "Terabytes/Second",
    "bit/s": "Bits/Second",
    "Kibit/s": "Kilobits/Second",
    "Mibit/s": "Megabits/Second",
    "Gibit/s": "Gigabits/Second",
    "Tibit/s": "Terabits/Second",
    # Count
    "1": "Count",
    "{request}": "Count",
    "{requests}": "Count",
    "{error}": "Count",
    "{errors}": "Count",
    "{operation}": "Count",
    "{packet}": "Count",
    "{connection}": "Count",
    # Percentage
    "%": "Percent",
}


def map_unit(otel_unit: Optional[str]) -> str:
    """Map an OpenTelemetry unit to a CloudWatch unit.

    Args:
        otel_unit: OpenTelemetry unit string (UCUM format)

    Returns:
        CloudWatch unit string, or "None" if no mapping exists
    """
    if not otel_unit:
        return "None"
    return OTEL_TO_CLOUDWATCH_UNITS.get(otel_unit, "None")
