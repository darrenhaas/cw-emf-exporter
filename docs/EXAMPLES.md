# Examples

## Table of Contents

- [Basic Usage](#basic-usage)
- [AWS Lambda](#aws-lambda)
- [ECS/Fargate](#ecsfargate)
- [EC2 with CloudWatch Agent](#ec2-with-cloudwatch-agent)
- [Metric Types](#metric-types)
- [Dimension Management](#dimension-management)
- [Testing and Development](#testing-and-development)
- [Framework Integration](#framework-integration)

---

## Basic Usage

### Minimal Setup

```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

# Create exporter with just namespace
exporter = CloudWatchEMFExporter(namespace="MyApp")

# Set up OpenTelemetry
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)

# Create metrics
meter = metrics.get_meter("my-service")
counter = meter.create_counter("requests", unit="1", description="Request count")

# Record metrics
counter.add(1, {"endpoint": "/api/users"})
```

### Complete Setup with All Options

```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

# Create resource with service info
resource = Resource.create({
    "service.name": "payment-service",
    "service.version": "1.2.3",
    "deployment.environment": "production",
})

# Create exporter with all options
exporter = CloudWatchEMFExporter(
    namespace="MyApp/Production",
    dimension_keys=["service.name", "endpoint", "status_code"],
    max_dimensions=10,
    storage_resolution=60,
    auto_detect_aws=True,
    histogram_as_values=True,
)

# Set up OpenTelemetry with resource
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)
```

---

## AWS Lambda

### Basic Lambda Handler

```python
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

# Initialize once outside handler (reused across invocations)
exporter = CloudWatchEMFExporter(
    namespace="MyLambda",
    dimension_keys=["operation", "status"],
    auto_detect_aws=True,  # Adds function_name, version, region, memory
)
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=1000)
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter("lambda-service")
invocations = meter.create_counter("invocations", unit="1")
latency = meter.create_histogram("latency", unit="ms")
errors = meter.create_counter("errors", unit="1")


def handler(event, context):
    import time
    start = time.time()

    try:
        # Your business logic
        result = process_event(event)

        invocations.add(1, {"operation": "process", "status": "success"})
        return result

    except Exception as e:
        errors.add(1, {"operation": "process", "status": "error"})
        raise

    finally:
        duration_ms = (time.time() - start) * 1000
        latency.record(duration_ms, {"operation": "process"})

        # Force flush before Lambda freezes
        provider.force_flush()
```

### Lambda with API Gateway

```python
import json
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

exporter = CloudWatchEMFExporter(
    namespace="MyAPI",
    dimension_keys=["method", "path", "status_code"],
    auto_detect_aws=True,
)
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=1000)
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter("api-gateway")
requests = meter.create_counter("http_requests", unit="1")
latency = meter.create_histogram("http_latency", unit="ms")


def handler(event, context):
    import time
    start = time.time()

    method = event.get("httpMethod", "UNKNOWN")
    path = event.get("path", "/")

    try:
        # Route to handler
        if path == "/users" and method == "GET":
            body = get_users()
            status_code = 200
        elif path == "/users" and method == "POST":
            body = create_user(json.loads(event.get("body", "{}")))
            status_code = 201
        else:
            body = {"error": "Not Found"}
            status_code = 404

    except Exception as e:
        body = {"error": str(e)}
        status_code = 500

    finally:
        duration_ms = (time.time() - start) * 1000
        attrs = {"method": method, "path": path, "status_code": str(status_code)}

        requests.add(1, attrs)
        latency.record(duration_ms, attrs)
        provider.force_flush()

    return {
        "statusCode": status_code,
        "body": json.dumps(body),
    }
```

---

## ECS/Fargate

### ECS Service with Periodic Export

```python
import time
import threading
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

# Create resource with ECS task info
resource = Resource.create({
    "service.name": "order-processor",
    "service.version": "2.0.0",
})

exporter = CloudWatchEMFExporter(
    namespace="MyECS/OrderService",
    dimension_keys=["service.name", "queue", "message_type"],
    auto_detect_aws=True,  # Adds aws_ecs=true, region, and ECS task metadata when available
)

# Export every 60 seconds
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter("order-processor")
messages_processed = meter.create_counter("messages_processed", unit="1")
processing_time = meter.create_histogram("processing_time", unit="ms")
queue_depth = meter.create_gauge("queue_depth", unit="1")


def process_message(message):
    start = time.time()
    message_type = message.get("type", "unknown")

    try:
        # Process the message
        handle_message(message)

        messages_processed.add(1, {
            "queue": "orders",
            "message_type": message_type,
            "status": "success",
        })
    except Exception as e:
        messages_processed.add(1, {
            "queue": "orders",
            "message_type": message_type,
            "status": "error",
        })
        raise
    finally:
        duration_ms = (time.time() - start) * 1000
        processing_time.record(duration_ms, {
            "queue": "orders",
            "message_type": message_type,
        })


def update_queue_metrics():
    """Background thread to report queue depth."""
    while True:
        depth = get_queue_depth("orders")
        queue_depth.set(depth, {"queue": "orders"})
        time.sleep(10)


# Start background metrics
threading.Thread(target=update_queue_metrics, daemon=True).start()
```

---

## EC2 with CloudWatch Agent

### Setup for CloudWatch Agent

```python
import os
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

# Get instance ID from metadata or environment
instance_id = os.environ.get("INSTANCE_ID", "unknown")

# Write to file that CloudWatch Agent monitors
with open("/var/log/myapp/emf.log", "a") as log_file:
    exporter = CloudWatchEMFExporter(
        namespace="MyEC2App",
        output=log_file,
        log_group_name="/aws/ec2/my-application",
        log_stream_name=instance_id,
        auto_detect_aws=True,
    )

    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
    provider = MeterProvider(metric_readers=[reader])
    metrics.set_meter_provider(provider)

    # ... use metrics
```

### CloudWatch Agent Configuration

Save to `/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json`:

```json
{
  "logs": {
    "logs_collected": {
      "files": {
        "collect_list": [
          {
            "file_path": "/var/log/myapp/emf.log",
            "log_group_name": "/aws/ec2/my-application",
            "log_stream_name": "{instance_id}",
            "timezone": "UTC"
          }
        ]
      }
    }
  }
}
```

---

## Metric Types

### Counter

```python
meter = metrics.get_meter("my-service")

# Simple counter
requests = meter.create_counter(
    "http_requests",
    unit="1",
    description="Total HTTP requests",
)

# Record
requests.add(1, {"method": "GET", "endpoint": "/users"})
requests.add(5, {"method": "POST", "endpoint": "/orders"})
```

**EMF Output:**
```json
{
  "_aws": {
    "Timestamp": 1700000000000,
    "CloudWatchMetrics": [{
      "Namespace": "MyApp",
      "Dimensions": [["method", "endpoint"]],
      "Metrics": [{"Name": "http_requests", "Unit": "Count", "StorageResolution": 60}]
    }]
  },
  "http_requests": 1,
  "method": "GET",
  "endpoint": "/users"
}
```

### UpDownCounter

```python
# Track values that go up and down
active_connections = meter.create_up_down_counter(
    "active_connections",
    unit="1",
    description="Current active connections",
)

# Connection opened
active_connections.add(1, {"server": "web-01"})

# Connection closed
active_connections.add(-1, {"server": "web-01"})
```

### Gauge

```python
# Point-in-time measurements
cpu_usage = meter.create_gauge(
    "cpu_usage",
    unit="%",
    description="CPU utilization percentage",
)

memory_usage = meter.create_gauge(
    "memory_usage",
    unit="By",
    description="Memory usage in bytes",
)

# Set current values
cpu_usage.set(75.5, {"host": "web-01"})
memory_usage.set(1073741824, {"host": "web-01"})  # 1 GB
```

### Histogram (with Percentiles)

```python
# Latency histogram - enables p50, p90, p99 in CloudWatch
latency = meter.create_histogram(
    "request_latency",
    unit="ms",
    description="Request latency distribution",
)

# Record observations
latency.record(45.2, {"endpoint": "/api/users"})
latency.record(123.5, {"endpoint": "/api/users"})
latency.record(12.1, {"endpoint": "/api/users"})
```

**EMF Output (histogram_as_values=True):**
```json
{
  "_aws": {
    "Timestamp": 1700000000000,
    "CloudWatchMetrics": [{
      "Namespace": "MyApp",
      "Dimensions": [["endpoint"]],
      "Metrics": [{"Name": "request_latency", "Unit": "Milliseconds", "StorageResolution": 60}]
    }]
  },
  "request_latency": [5, 5, 15, 15, 15],
  "endpoint": "/api/users"
}
```

The exact histogram values depend on the OpenTelemetry bucket boundaries. The
exporter emits bucket representatives repeated by bucket count, capped at 100
values per EMF document.

### Histogram (Derived Metrics Mode)

```python
exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    histogram_as_values=False,  # Emit _count/_sum/_min/_max
)
```

**EMF Output (histogram_as_values=False):**
```json
{
  "_aws": {
    "Timestamp": 1700000000000,
    "CloudWatchMetrics": [{
      "Namespace": "MyApp",
      "Dimensions": [["endpoint"]],
      "Metrics": [
        {"Name": "request_latency_count", "Unit": "Count", "StorageResolution": 60},
        {"Name": "request_latency_sum", "Unit": "Milliseconds", "StorageResolution": 60},
        {"Name": "request_latency_min", "Unit": "Milliseconds", "StorageResolution": 60},
        {"Name": "request_latency_max", "Unit": "Milliseconds", "StorageResolution": 60}
      ]
    }]
  },
  "request_latency_count": 3,
  "request_latency_sum": 180.8,
  "request_latency_min": 12.1,
  "request_latency_max": 123.5,
  "endpoint": "/api/users"
}
```

---

## Dimension Management

### Filtering High-Cardinality Attributes

```python
# Risky: all attributes become dimensions.
exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    dimension_keys=None,
)

# Preferred: include only stable dimensions.
exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    dimension_keys=["service", "environment", "status_code"],
)
```

### Combining Resource and Metric Attributes

```python
from opentelemetry.sdk.resources import Resource

# Resource attributes (low priority)
resource = Resource.create({
    "service.name": "api-gateway",
    "deployment.environment": "production",
    "service.version": "1.0.0",
})

exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    dimension_keys=["service.name", "deployment.environment", "endpoint"],
)

provider = MeterProvider(resource=resource, metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter("api")
counter = meter.create_counter("requests", unit="1")

# Metric attributes (high priority - can override resource)
counter.add(1, {"endpoint": "/users"})

# Result dimensions: service.name=api-gateway, deployment.environment=production, endpoint=/users
```

### Limiting Dimension Count

```python
# CloudWatch allows max 30 dimensions
# Use max_dimensions to prevent exceeding limit

exporter = CloudWatchEMFExporter(
    namespace="MyApp",
    max_dimensions=10,  # Only first 10 dimensions kept
)
```

---

## Testing and Development

### Capturing EMF Output for Testing

```python
import io
import json
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

def test_metrics_export():
    # Capture output in buffer
    buffer = io.StringIO()

    exporter = CloudWatchEMFExporter(
        namespace="TestApp",
        output=buffer,
        auto_detect_aws=False,  # Disable for consistent tests
    )

    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=100)
    provider = MeterProvider(metric_readers=[reader])
    metrics.set_meter_provider(provider)

    # Create and record metric
    meter = metrics.get_meter("test")
    counter = meter.create_counter("test_counter", unit="1")
    counter.add(42, {"test_dim": "value"})

    # Force export
    provider.force_flush()

    # Parse and verify EMF output
    output = buffer.getvalue()
    for line in output.strip().split("\n"):
        emf = json.loads(line)
        assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "TestApp"
        assert emf["test_counter"] == 42
        assert emf["test_dim"] == "value"

    # Cleanup
    provider.shutdown()
```

### Using Custom Timestamp for Reproducible Tests

```python
def test_with_fixed_timestamp():
    fixed_time = 1700000000000  # Fixed timestamp

    exporter = CloudWatchEMFExporter(
        namespace="TestApp",
        timestamp_fn=lambda: fixed_time,
        auto_detect_aws=False,
    )

    # All EMF output will have Timestamp: 1700000000000
```

### Mocking AWS Environment

```python
import os
from unittest.mock import patch

def test_lambda_detection():
    env_vars = {
        "AWS_LAMBDA_FUNCTION_NAME": "my-function",
        "AWS_LAMBDA_FUNCTION_VERSION": "$LATEST",
        "AWS_REGION": "us-east-1",
        "AWS_LAMBDA_FUNCTION_MEMORY_SIZE": "512",
    }

    with patch.dict(os.environ, env_vars):
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            auto_detect_aws=True,
        )
        # Exporter will include Lambda dimensions
```

---

## Framework Integration

### FastAPI

```python
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

# Global metrics
provider = None
meter = None
request_counter = None
request_latency = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global provider, meter, request_counter, request_latency

    # Setup
    exporter = CloudWatchEMFExporter(
        namespace="FastAPIApp",
        dimension_keys=["method", "path", "status_code"],
    )
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
    provider = MeterProvider(metric_readers=[reader])
    metrics.set_meter_provider(provider)

    meter = metrics.get_meter("fastapi")
    request_counter = meter.create_counter("http_requests", unit="1")
    request_latency = meter.create_histogram("http_latency", unit="ms")

    yield

    # Shutdown
    provider.shutdown()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration_ms = (time.time() - start) * 1000

    attrs = {
        "method": request.method,
        "path": request.url.path,
        "status_code": str(response.status_code),
    }

    request_counter.add(1, attrs)
    request_latency.record(duration_ms, attrs)

    return response


@app.get("/users")
async def get_users():
    return {"users": []}


@app.get("/health")
async def health():
    return {"status": "healthy"}
```

### Flask

```python
import time
from flask import Flask, request, g
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

app = Flask(__name__)

# Setup metrics
exporter = CloudWatchEMFExporter(
    namespace="FlaskApp",
    dimension_keys=["method", "endpoint", "status_code"],
)
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter("flask")
request_counter = meter.create_counter("http_requests", unit="1")
request_latency = meter.create_histogram("http_latency", unit="ms")


@app.before_request
def before_request():
    g.start_time = time.time()


@app.after_request
def after_request(response):
    duration_ms = (time.time() - g.start_time) * 1000

    attrs = {
        "method": request.method,
        "endpoint": request.endpoint or "unknown",
        "status_code": str(response.status_code),
    }

    request_counter.add(1, attrs)
    request_latency.record(duration_ms, attrs)

    return response


@app.route("/users")
def get_users():
    return {"users": []}


@app.route("/health")
def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    try:
        app.run()
    finally:
        provider.shutdown()
```

### Django (with middleware)

```python
# settings.py
MIDDLEWARE = [
    # ... other middleware
    'myapp.middleware.MetricsMiddleware',
]

# myapp/metrics.py
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter

exporter = CloudWatchEMFExporter(
    namespace="DjangoApp",
    dimension_keys=["method", "view", "status_code"],
)
reader = PeriodicExportingMetricReader(exporter, export_interval_millis=60000)
provider = MeterProvider(metric_readers=[reader])
metrics.set_meter_provider(provider)

meter = metrics.get_meter("django")
request_counter = meter.create_counter("http_requests", unit="1")
request_latency = meter.create_histogram("http_latency", unit="ms")

# myapp/middleware.py
import time
from django.urls import resolve
from .metrics import request_counter, request_latency


class MetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.time()
        response = self.get_response(request)
        duration_ms = (time.time() - start) * 1000

        try:
            view_name = resolve(request.path).view_name
        except Exception:
            view_name = "unknown"

        attrs = {
            "method": request.method,
            "view": view_name,
            "status_code": str(response.status_code),
        }

        request_counter.add(1, attrs)
        request_latency.record(duration_ms, attrs)

        return response
```

---

## High-Resolution Metrics

### Real-Time Monitoring

```python
# Use 1-second resolution for real-time dashboards
# Note: Data only retained for 3 hours

exporter = CloudWatchEMFExporter(
    namespace="MyApp/RealTime",
    storage_resolution=1,  # High resolution
)

reader = PeriodicExportingMetricReader(
    exporter,
    export_interval_millis=1000,  # Export every second
)
```

### Mixed Resolution

```python
# For mixed requirements, use separate exporters

# Standard resolution for most metrics (cheaper, longer retention)
standard_exporter = CloudWatchEMFExporter(
    namespace="MyApp/Standard",
    storage_resolution=60,
)

# High resolution for critical real-time metrics
realtime_exporter = CloudWatchEMFExporter(
    namespace="MyApp/RealTime",
    storage_resolution=1,
)

# Use different meter providers or manual export calls
```
