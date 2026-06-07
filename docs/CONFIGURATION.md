# Configuration Guide

## Constructor Parameters

```python
CloudWatchEMFExporter(
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
)
```

## Parameter Reference

### Required Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `namespace` | `str` | CloudWatch metrics namespace. Must be 1-256 characters. |

### Output Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `output` | `TextIO` | `sys.stdout` | Output stream for EMF JSON lines. |
| `timestamp_fn` | `Callable[[], int]` | Current time | Function returning epoch milliseconds. |

### Dimension Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dimension_keys` | `List[str]` | `None` | Whitelist of attribute keys to use as dimensions. `None` = all attributes. |
| `max_dimensions` | `int` | `30` | Maximum dimensions per metric. CloudWatch limit is 30. |

### Resolution Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `storage_resolution` | `int` | `60` | `1` = high-resolution (1-second), `60` = standard (1-minute). |

### Log Routing Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `log_group_name` | `str` | `None` | CloudWatch Log Group name for EMF routing. |
| `log_stream_name` | `str` | `None` | CloudWatch Log Stream name for EMF routing. |

### Feature Flags

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `auto_detect_aws` | `bool` | `True` | Auto-detect Lambda/ECS/EC2 environment and add dimensions. |
| `histogram_as_values` | `bool` | `True` | Emit histograms as Values arrays (enables percentiles). |

---

## Configuration Examples

### Minimal Configuration

```python
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

exporter = CloudWatchEMFExporter(namespace="MyApp")
```

### Production Lambda Configuration

```python
exporter = CloudWatchEMFExporter(
    namespace="MyApp/Production",
    dimension_keys=["service", "operation", "status_code"],
    max_dimensions=10,
    storage_resolution=60,
    histogram_as_values=True,
    auto_detect_aws=True,  # Auto-adds Lambda dimensions
)
```

### High-Resolution Metrics

```python
exporter = CloudWatchEMFExporter(
    namespace="MyApp/RealTime",
    storage_resolution=1,  # 1-second resolution
    histogram_as_values=True,
)
```

### EC2 with CloudWatch Agent

```python
exporter = CloudWatchEMFExporter(
    namespace="MyApp/EC2",
    log_group_name="/aws/ec2/my-application",
    log_stream_name="i-1234567890abcdef0",
    auto_detect_aws=True,
)
```

### Custom Output Stream

```python
import io

buffer = io.StringIO()
exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    output=buffer,
)

# Later: get all EMF output
emf_output = buffer.getvalue()
```

### File Output

```python
with open("/var/log/emf.log", "a") as f:
    exporter = CloudWatchEMFExporter(
        namespace="MyApp",
        output=f,
    )
    # ... use exporter
```

### Disable AWS Auto-Detection

```python
exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    auto_detect_aws=False,  # Do not add Lambda/ECS/EC2 dimensions
)
```

### Derived Histogram Metrics

```python
exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    histogram_as_values=False,  # Emit _count/_sum/_min/_max
)
```

### Custom Timestamp

```python
def get_custom_timestamp():
    # Use a specific timestamp source
    return int(my_time_source.now() * 1000)

exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    timestamp_fn=get_custom_timestamp,
)
```

---

## Dimension Filtering

### Why Filter Dimensions?

CloudWatch creates a distinct metric for each unique dimension set. Avoid using
request IDs, user IDs, full URLs, or other high-cardinality values as
dimensions. Prefer stable dimensions such as service, environment, operation,
method, route, or status code.

| Attribute Pattern | Dimension Fit |
|-------------------|---------------|
| `service.name`, `deployment.environment`, `http.method` | Good default candidates |
| Route templates such as `/users/{id}` | Usually acceptable |
| Full URLs, request IDs, user IDs | Avoid |

### Dimension Priority

Dimensions are merged in this order:

1. AWS environment attributes when `auto_detect_aws=True`.
2. OpenTelemetry resource attributes.
3. Metric point attributes. These take precedence over earlier values.

After merging, `dimension_keys` is applied when set, and the result is capped at
`max_dimensions`.

---

## Storage Resolution

### Resolution Comparison

| Resolution | Value | Data Retention | Cost | Use Case |
|------------|-------|---------------|------|----------|
| Standard | `60` | 15 days (1-min), 63 days (5-min), 15 months (1-hour) | Lower | Most applications |
| High | `1` | 3 hours only | Higher | Real-time monitoring, incident response |

### When to Use High Resolution

| Use High Resolution For | Prefer Standard Resolution For |
|-------------------------|--------------------------------|
| Real-time dashboards requiring sub-minute updates | Long-term trend analysis |
| Incident response metrics | Cost-sensitive environments |
| Performance testing with precise timing | Low-frequency metrics |

---

## AWS Environment Integration

### Lambda

```python
# Lambda auto-detection adds these dimensions:
# - aws_lambda_function_name
# - aws_lambda_function_version
# - aws_region
# - aws_lambda_memory

exporter = CloudWatchEMFExporter(
    namespace="MyLambda",
    auto_detect_aws=True,  # Default
)
```

### ECS/Fargate

```python
# ECS auto-detection adds these dimensions:
# - aws_ecs = "true"
# - aws_region
# - aws_ecs_cluster
# - aws_ecs_task_arn
# - aws_ecs_task_family
# - aws_ecs_task_revision
# - aws_ecs_container_name

exporter = CloudWatchEMFExporter(
    namespace="MyECSService",
    auto_detect_aws=True,
)
```

ECS metadata is fetched from the task metadata endpoint with a short timeout. If
the endpoint is unavailable, the exporter still initializes and emits the basic
ECS markers it can infer from environment variables.

### EC2 with CloudWatch Agent

```python
# For EC2, configure log routing so CloudWatch Agent picks up the EMF:

exporter = CloudWatchEMFExporter(
    namespace="MyEC2App",
    log_group_name="/aws/ec2/my-application",
    log_stream_name=os.environ.get("HOSTNAME", "unknown"),
)
```

CloudWatch Agent config (`/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json`):
```json
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/my-app/emf.log",
            "log_group_name": "/aws/ec2/my-application",
            "log_stream_name": "{instance_id}"
          }
        ]
      }
    }
  }
}
```

---

## Histogram Configuration

### Values Mode (Default)

```python
# Enables percentile calculations (p50, p90, p99, etc.)
exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    histogram_as_values=True,  # Default
)
```

Output:
```json
{
  "request_latency": [5, 5, 15, 15, 15],
  ...
}
```

The exporter uses bucket midpoints as representative values and repeats them
according to bucket counts. If a histogram has more than 100 observations in an
export cycle, values are sampled proportionally to stay within EMF's numeric
array limit.

### Derived Metrics Mode

```python
# Emits _count, _sum, _min, _max (no percentiles)
exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    histogram_as_values=False,
)
```

Output:
```json
{
  "request_latency_count": 100,
  "request_latency_sum": 5000,
  "request_latency_min": 10,
  "request_latency_max": 200,
  ...
}
```

### Comparison

| Feature | `histogram_as_values=True` | `histogram_as_values=False` |
|---------|---------------------------|----------------------------|
| Percentiles (p50, p99) | Supported | Not supported |
| Count/Sum/Min/Max | Computed by CloudWatch | Emitted as explicit metrics |
| EMF Size | Larger (array of values) | Smaller (4 values) |
| Metric Count | 1 per histogram | 4 per histogram |
