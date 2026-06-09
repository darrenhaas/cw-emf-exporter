"""OpenTelemetry metrics exporter for AWS CloudWatch using Embedded Metric Format (EMF).

This exporter converts OpenTelemetry metrics to CloudWatch Embedded Metric Format (EMF)
and prints them to stdout. When running in AWS (Lambda, ECS, App Runner, etc.),
CloudWatch Logs automatically parses EMF JSON and creates CloudWatch Metrics.

Example usage:
    from opentelemetry import metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

    exporter = CloudWatchEMFExporter(namespace="MyApplication")
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
    provider = MeterProvider(metric_readers=[reader])
    metrics.set_meter_provider(provider)

    meter = metrics.get_meter("my-meter")
    counter = meter.create_counter("requests", unit="1", description="Request count")
    counter.add(1, {"endpoint": "/api/users"})
"""

from opentelemetry_exporter_cloudwatch_emf.exporter import CloudWatchEMFExporter

__all__ = ["CloudWatchEMFExporter"]
__version__ = "0.2.5"
