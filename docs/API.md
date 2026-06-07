# API Reference

## CloudWatchEMFExporter

Main exporter class that implements the OpenTelemetry `MetricExporter` interface.

### Class Definition

```python
class CloudWatchEMFExporter(MetricExporter):
    """OpenTelemetry metrics exporter using CloudWatch Embedded Metric Format."""
```

### Constructor

```python
def __init__(
    self,
    namespace: str,
    output: TextIO = sys.stdout,
    timestamp_fn: Optional[Callable[[], int]] = None,
    dimension_keys: Optional[List[str]] = None,
    max_dimensions: int = 30,
    storage_resolution: int = 60,
    log_group_name: Optional[str] = None,
    log_stream_name: Optional[str] = None,
    auto_detect_aws: bool = True,
    histogram_as_values: bool = True,
) -> None
```

#### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `namespace` | `str` | Yes | - | CloudWatch metrics namespace (1-256 chars) |
| `output` | `TextIO` | No | `sys.stdout` | Output stream for EMF JSON |
| `timestamp_fn` | `Callable[[], int]` | No | `None` | Custom timestamp function (epoch ms) |
| `dimension_keys` | `List[str]` | No | `None` | Whitelist of dimension keys |
| `max_dimensions` | `int` | No | `30` | Max dimensions per metric (0-30) |
| `storage_resolution` | `int` | No | `60` | Storage resolution (1 or 60) |
| `log_group_name` | `str` | No | `None` | CloudWatch Log Group for routing |
| `log_stream_name` | `str` | No | `None` | CloudWatch Log Stream for routing |
| `auto_detect_aws` | `bool` | No | `True` | Auto-detect AWS environment |
| `histogram_as_values` | `bool` | No | `True` | Emit histograms as Values arrays |

#### Raises

| Exception | Condition |
|-----------|-----------|
| `ValueError` | `namespace` is empty or > 256 characters |
| `ValueError` | `storage_resolution` is not 1 or 60 |
| `ValueError` | `max_dimensions` is < 0 or > 30 |

#### Example

```python
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

exporter = CloudWatchEMFExporter(
    namespace="MyApplication",
    dimension_keys=["service", "environment"],
    storage_resolution=60,
)
```

---

### Methods

#### export

```python
def export(
    self,
    metrics_data: MetricsData,
    timeout_millis: float = 10000,
    **kwargs: Any,
) -> MetricExportResult
```

Exports metrics as EMF JSON to the configured output stream.

##### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `metrics_data` | `MetricsData` | Yes | - | OpenTelemetry metrics to export |
| `timeout_millis` | `float` | No | `10000` | Timeout (unused, export is synchronous) |

##### Returns

| Return | Type | Description |
|--------|------|-------------|
| Success | `MetricExportResult.SUCCESS` | All metrics exported successfully |
| Failure | `MetricExportResult.FAILURE` | Export failed or exporter is shutdown |

##### Example

```python
from opentelemetry.sdk.metrics.export import MetricExportResult

result = exporter.export(metrics_data)
if result == MetricExportResult.SUCCESS:
    print("Metrics exported")
```

---

#### force_flush

```python
def force_flush(self, timeout_millis: float = 10000) -> bool
```

Flushes any buffered data to the output stream.

##### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `timeout_millis` | `float` | No | `10000` | Timeout (unused) |

##### Returns

| Return | Type | Description |
|--------|------|-------------|
| `True` | `bool` | Flush succeeded |
| `False` | `bool` | Flush failed |

##### Example

```python
success = exporter.force_flush()
```

---

#### shutdown

```python
def shutdown(self, timeout_millis: float = 30000, **kwargs: Any) -> None
```

Shuts down the exporter. After shutdown, `export()` will return `FAILURE`.

##### Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `timeout_millis` | `float` | No | `30000` | Timeout (unused) |

##### Example

```python
exporter.shutdown()
```

---

## Helper Functions

### _detect_aws_environment

```python
def _detect_aws_environment() -> Dict[str, str]
```

Detects AWS environment (Lambda, ECS, EC2) from environment variables.

#### Returns

Dictionary of detected AWS attributes:

| Environment | Attributes |
|-------------|------------|
| Lambda | `aws_lambda_function_name`, `aws_lambda_function_version`, `aws_region`, `aws_lambda_memory` |
| ECS | `aws_ecs`, `aws_region`, `aws_ecs_cluster`, `aws_ecs_task_arn`, `aws_ecs_task_family`, `aws_ecs_task_revision`, `aws_ecs_container_name` |
| EC2/Generic | `aws_region` |
| Non-AWS | `{}` (empty dict) |

ECS metadata is fetched from the task metadata endpoint with a short timeout.
Metadata lookup failures are ignored and do not fail exporter initialization.

#### Example

```python
from opentelemetry_exporter_cloudwatch_emf.exporter import _detect_aws_environment

attrs = _detect_aws_environment()
# {'aws_lambda_function_name': 'my-func', 'aws_region': 'us-east-1', ...}
```

---

### _sanitize_metric_name

```python
def _sanitize_metric_name(name: str) -> str
```

Sanitizes a metric name for CloudWatch compatibility.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Original metric name |

#### Returns

Sanitized metric name (max 256 characters).

#### Transformations

| Input | Output | Rule |
|-------|--------|------|
| `aws::lambda::invocations` | `aws_lambda_invocations` | `::` → `_` |
| `metric:name` | `metric_name` | `:` → `_` |
| `metric@name#test` | `metricnametest` | Invalid chars removed |
| `_metric` | `m_metric` | Leading non-alnum fixed |
| `x` * 300 | `x` * 256 | Truncated |

#### Example

```python
from opentelemetry_exporter_cloudwatch_emf.exporter import _sanitize_metric_name

name = _sanitize_metric_name("aws::lambda::invocations")
# "aws_lambda_invocations"
```

---

## Unit Mapping

### map_unit

```python
def map_unit(otel_unit: Optional[str]) -> str
```

Maps OpenTelemetry UCUM units to CloudWatch units.

#### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `otel_unit` | `Optional[str]` | OpenTelemetry unit string |

#### Returns

CloudWatch unit string. Returns `"None"` for unknown units.

#### Mapping Table

| OpenTelemetry | CloudWatch |
|---------------|------------|
| `s` | `Seconds` |
| `ms` | `Milliseconds` |
| `us` | `Microseconds` |
| `ns` | `Microseconds` |
| `By` | `Bytes` |
| `KiBy` | `Kilobytes` |
| `MiBy` | `Megabytes` |
| `GiBy` | `Gigabytes` |
| `TiBy` | `Terabytes` |
| `bit` | `Bits` |
| `Kibit` | `Kilobits` |
| `Mibit` | `Megabits` |
| `Gibit` | `Gigabits` |
| `Tibit` | `Terabits` |
| `By/s` | `Bytes/Second` |
| `KiBy/s` | `Kilobytes/Second` |
| `MiBy/s` | `Megabytes/Second` |
| `GiBy/s` | `Gigabytes/Second` |
| `TiBy/s` | `Terabytes/Second` |
| `bit/s` | `Bits/Second` |
| `Kibit/s` | `Kilobits/Second` |
| `Mibit/s` | `Megabits/Second` |
| `Gibit/s` | `Gigabits/Second` |
| `Tibit/s` | `Terabits/Second` |
| `1` | `Count` |
| `{request}` | `Count` |
| `{error}` | `Count` |
| `{packet}` | `Count` |
| `{connection}` | `Count` |
| `%` | `Percent` |
| (unknown) | `None` |

#### Example

```python
from opentelemetry_exporter_cloudwatch_emf.units import map_unit

unit = map_unit("ms")      # "Milliseconds"
unit = map_unit("By")      # "Bytes"
unit = map_unit("unknown") # "None"
```

---

## EMF Output Format

### Single Metric

```json
{
  "_aws": {
    "Timestamp": 1700000000000,
    "CloudWatchMetrics": [{
      "Namespace": "MyApplication",
      "Dimensions": [["service", "endpoint"]],
      "Metrics": [{
        "Name": "request_count",
        "Unit": "Count",
        "StorageResolution": 60
      }]
    }]
  },
  "request_count": 42,
  "service": "api",
  "endpoint": "/users"
}
```

### Multiple Metrics (Histogram Derived)

```json
{
  "_aws": {
    "Timestamp": 1700000000000,
    "CloudWatchMetrics": [{
      "Namespace": "MyApplication",
      "Dimensions": [["service"]],
      "Metrics": [
        {"Name": "latency_count", "Unit": "Count", "StorageResolution": 60},
        {"Name": "latency_sum", "Unit": "Milliseconds", "StorageResolution": 60},
        {"Name": "latency_min", "Unit": "Milliseconds", "StorageResolution": 60},
        {"Name": "latency_max", "Unit": "Milliseconds", "StorageResolution": 60}
      ]
    }]
  },
  "latency_count": 100,
  "latency_sum": 5000,
  "latency_min": 10,
  "latency_max": 200,
  "service": "api"
}
```

### Values Array (Histogram)

```json
{
  "_aws": {
    "Timestamp": 1700000000000,
    "CloudWatchMetrics": [{
      "Namespace": "MyApplication",
      "Dimensions": [["service"]],
      "Metrics": [{
        "Name": "latency",
        "Unit": "Milliseconds",
        "StorageResolution": 60
      }]
    }]
  },
  "latency": [5, 5, 15, 15, 15],
  "service": "api"
}
```

Histogram values are bucket representatives repeated by count. Large histograms
are proportionally sampled to stay within EMF's 100-value numeric array limit.

### With Log Routing

```json
{
  "_aws": {
    "Timestamp": 1700000000000,
    "LogGroupName": "/aws/ec2/my-application",
    "LogStreamName": "i-1234567890abcdef0",
    "CloudWatchMetrics": [{
      "Namespace": "MyApplication",
      "Dimensions": [["service"]],
      "Metrics": [{
        "Name": "request_count",
        "Unit": "Count",
        "StorageResolution": 60
      }]
    }]
  },
  "request_count": 42,
  "service": "api"
}
```
