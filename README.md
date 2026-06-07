# OpenTelemetry CloudWatch EMF Exporter

[![PyPI](https://img.shields.io/pypi/v/opentelemetry-exporter-cloudwatch-emf.svg)](https://pypi.org/project/opentelemetry-exporter-cloudwatch-emf/)
[![Python Versions](https://img.shields.io/pypi/pyversions/opentelemetry-exporter-cloudwatch-emf.svg)](https://pypi.org/project/opentelemetry-exporter-cloudwatch-emf/)
[![License](https://img.shields.io/pypi/l/opentelemetry-exporter-cloudwatch-emf.svg)](LICENSE)

An OpenTelemetry metrics exporter for AWS CloudWatch using [Embedded Metric Format (EMF)](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format.html).

This is an unofficial community project. It is not affiliated with, endorsed by,
or maintained by Amazon Web Services (AWS), Amazon CloudWatch, or the
OpenTelemetry project.

## Why This Exporter?

OpenTelemetry and AWS support CloudWatch EMF primarily through Collector or
CloudWatch Agent workflows. This package covers the collectorless Python SDK use
case: emit valid CloudWatch EMF JSON directly from a Python metrics exporter and
let Lambda, ECS/Fargate, or EC2 log collection deliver it to CloudWatch Logs.

| Approach | Runtime Model | Operational Fit |
|----------|---------------|-----------------|
| ADOT Collector | Separate collector process | Full collector pipeline and AWS-managed integration |
| ADOT Lambda Layer | Embedded collector layer | Lambda workloads that need Collector features |
| **This Exporter** | In-process Python SDK exporter | Collectorless workloads that emit EMF through stdout or logs |

## Installation

```bash
pip install opentelemetry-exporter-cloudwatch-emf
```

To install a specific source release from GitHub:

```bash
pip install git+ssh://git@github.com/darrenhaas/cw-emf-exporter.git@v0.2.4
```

## Quick Start

```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

# Create exporter
exporter = CloudWatchEMFExporter(namespace="MyApplication")

# Set up meter provider
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)

# Create and use metrics
meter = metrics.get_meter("my-service")
counter = meter.create_counter("requests", unit="1")
counter.add(1, {"endpoint": "/api/users", "method": "GET"})
```

The exporter writes one EMF JSON document per metric batch to the configured
output stream. By default, that stream is `sys.stdout`.

## Documentation

| Document | Description |
|----------|-------------|
| [Architecture](docs/ARCHITECTURE.md) | System design, data flow, components |
| [Configuration](docs/CONFIGURATION.md) | All options with examples |
| [API Reference](docs/API.md) | Public API and helper behavior |
| [Examples](docs/EXAMPLES.md) | Usage patterns and recipes |
| [Release Process](docs/RELEASE.md) | PyPI release checklist |
| [Changelog](CHANGELOG.md) | Release history |
| [Project Notice](docs/NOTICE.md) | Unofficial project and trademark notice |
| [Community Gap](docs/COMMUNITY_GAP.md) | Upstream context for collectorless Python EMF export |

## Features

### Metric Types Support

| OTel Metric Type | EMF Output | Percentile Support |
|-----------------|------------|-------------------|
| Counter | Single value | N/A |
| Gauge | Single value | N/A |
| Histogram | Values array | Yes (p50, p99, etc.) |
| ExponentialHistogram | Values array | Yes (p50, p99, etc.) |

### AWS Environment Auto-Detection

When `auto_detect_aws=True`, the exporter adds stable AWS environment
dimensions when it can detect them.

| Environment | Detection Signal | Added Dimensions |
|-------------|------------------|------------------|
| Lambda | `AWS_LAMBDA_FUNCTION_NAME` | Function name, version, region, memory size |
| ECS/Fargate | `ECS_CONTAINER_METADATA_URI` | ECS marker, region, selected task metadata |
| EC2/generic AWS | `AWS_REGION` | Region |

### Unit Mapping

| OpenTelemetry (UCUM) | CloudWatch Unit |
|---------------------|-----------------|
| `s` | Seconds |
| `ms` | Milliseconds |
| `us` | Microseconds |
| `By` | Bytes |
| `KiBy` | Kilobytes |
| `MiBy` | Megabytes |
| `GiBy` | Gigabytes |
| `TiBy` | Terabytes |
| `By/s` | Bytes/Second |
| `1`, `{request}`, `{error}` | Count |
| `%` | Percent |

## Configuration Summary

```python
CloudWatchEMFExporter(
    # Required
    namespace="MyApp",              # CloudWatch namespace (1-256 chars)

    # Output
    output=sys.stdout,              # Where to write EMF JSON

    # Dimensions
    dimension_keys=["svc", "env"],  # Filter dimensions (None = all)
    max_dimensions=30,              # Max dimensions (CloudWatch limit: 30)

    # Resolution
    storage_resolution=60,          # 1 = high-res, 60 = standard

    # Log Routing (for CloudWatch Agent)
    log_group_name="/aws/myapp",    # Target log group
    log_stream_name="stream-1",     # Target log stream

    # Features
    auto_detect_aws=True,           # Auto-detect Lambda/ECS/EC2
    histogram_as_values=True,       # Enable percentile calculations

    # Advanced
    timestamp_fn=lambda: int(time.time() * 1000),  # Custom timestamp
)
```

## EMF Output Format

```json
{
  "_aws": {
    "Timestamp": 1700000000000,
    "CloudWatchMetrics": [{
      "Namespace": "MyApplication",
      "Dimensions": [["service", "endpoint"]],
      "Metrics": [{
        "Name": "request_latency",
        "Unit": "Milliseconds",
        "StorageResolution": 60
      }]
    }]
  },
  "request_latency": [5, 5, 15, 15, 15],
  "service": "api",
  "endpoint": "/users"
}
```

Histogram values use bucket representatives repeated by bucket count. Large
histograms are proportionally sampled to fit EMF's 100-value numeric array
limit.

## Development

```bash
# Install dev dependencies
uv sync --extra dev

# Run tests
uv run pytest

# Lint, type check, and package validation
uv run flake8 src tests
uv run mypy src
uv run black --check src tests
uv build
uv run twine check dist/*
```

## License

Apache 2.0 - See [LICENSE](LICENSE)
