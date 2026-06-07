# Architecture

## System Overview

The CloudWatch EMF Exporter is a Python library that bridges OpenTelemetry metrics to AWS CloudWatch without requiring a collector sidecar.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              SYSTEM ARCHITECTURE                                 │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                         APPLICATION LAYER                                │   │
│  │                                                                         │   │
│  │   ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────────────────┐      │   │
│  │   │ Counter │  │  Gauge  │  │Histogram│  │ ExponentialHistogram │      │   │
│  │   └────┬────┘  └────┬────┘  └────┬────┘  └──────────┬───────────┘      │   │
│  │        │            │            │                   │                  │   │
│  │        └────────────┴─────┬──────┴───────────────────┘                  │   │
│  │                           │                                             │   │
│  │                           ▼                                             │   │
│  │                  ┌─────────────────┐                                    │   │
│  │                  │  OpenTelemetry  │                                    │   │
│  │                  │   Metrics SDK   │                                    │   │
│  │                  └────────┬────────┘                                    │   │
│  │                           │                                             │   │
│  └───────────────────────────┼─────────────────────────────────────────────┘   │
│                              │                                                  │
│  ┌───────────────────────────┼─────────────────────────────────────────────┐   │
│  │                           ▼              EXPORTER LAYER                  │   │
│  │            ┌──────────────────────────────┐                             │   │
│  │            │   CloudWatchEMFExporter      │                             │   │
│  │            │                              │                             │   │
│  │            │  ┌────────────────────────┐  │                             │   │
│  │            │  │   MetricExporter       │  │  (OTel Interface)           │   │
│  │            │  │   • export()           │  │                             │   │
│  │            │  │   • force_flush()      │  │                             │   │
│  │            │  │   • shutdown()         │  │                             │   │
│  │            │  └────────────────────────┘  │                             │   │
│  │            │                              │                             │   │
│  │            │  ┌────────────────────────┐  │                             │   │
│  │            │  │   Internal Components  │  │                             │   │
│  │            │  │   • _export_metric()   │  │                             │   │
│  │            │  │   • _build_dimensions()│  │                             │   │
│  │            │  │   • _build_emf_doc()   │  │                             │   │
│  │            │  │   • _write_emf()       │  │                             │   │
│  │            │  └────────────────────────┘  │                             │   │
│  │            │                              │                             │   │
│  │            │  ┌────────────────────────┐  │                             │   │
│  │            │  │   Support Modules      │  │                             │   │
│  │            │  │   • units.py (mapping) │  │                             │   │
│  │            │  │   • AWS detection      │  │                             │   │
│  │            │  └────────────────────────┘  │                             │   │
│  │            └──────────────────────────────┘                             │   │
│  │                           │                                             │   │
│  └───────────────────────────┼─────────────────────────────────────────────┘   │
│                              │                                                  │
│                              ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                          OUTPUT LAYER                                    │   │
│  │                                                                         │   │
│  │   stdout ──────────────────────────────────────────────────────────►   │   │
│  │              EMF JSON (one line per metric batch)                       │   │
│  │                                                                         │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                               DATA FLOW                                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   1. COLLECTION                    2. AGGREGATION                               │
│   ─────────────                    ───────────────                              │
│                                                                                 │
│   counter.add(1, attrs)  ──►  ┌─────────────────┐                               │
│   gauge.set(42, attrs)   ──►  │  MetricReader   │                               │
│   histogram.record(ms)   ──►  │  (periodic)     │                               │
│                               └────────┬────────┘                               │
│                                        │                                        │
│                                        ▼                                        │
│   3. EXPORT                                                                     │
│   ─────────                                                                     │
│                                                                                 │
│   ┌────────────────────────────────────────────────────────────────────────┐   │
│   │                         export(metrics_data)                            │   │
│   │                                                                        │   │
│   │   MetricsData                                                          │   │
│   │   └── ResourceMetrics[]                                                │   │
│   │       └── resource.attributes  ──────────────────┐                     │   │
│   │       └── ScopeMetrics[]                         │                     │   │
│   │           └── Metric                             │                     │   │
│   │               ├── name ─────────────────────┐    │                     │   │
│   │               ├── unit ─────────────────┐   │    │                     │   │
│   │               └── data                  │   │    │                     │   │
│   │                   └── data_points[]     │   │    │                     │   │
│   │                       ├── value ────┐   │   │    │                     │   │
│   │                       └── attrs ──┐ │   │   │    │                     │   │
│   │                                   │ │   │   │    │                     │   │
│   └───────────────────────────────────┼─┼───┼───┼────┼─────────────────────┘   │
│                                       │ │   │   │    │                         │
│                                       ▼ ▼   ▼   ▼    ▼                         │
│   4. TRANSFORMATION                                                            │
│   ─────────────────                                                            │
│                                                                                 │
│   ┌────────────────────────────────────────────────────────────────────────┐   │
│   │                                                                        │   │
│   │   _build_dimensions()          _sanitize_metric_name()                 │   │
│   │   ┌──────────────────┐         ┌──────────────────┐                    │   │
│   │   │ • Merge attrs    │         │ • Replace ::     │                    │   │
│   │   │ • Add AWS env    │         │ • Remove invalid │                    │   │
│   │   │ • Filter keys    │         │ • Truncate 256   │                    │   │
│   │   │ • Sanitize names │         └──────────────────┘                    │   │
│   │   │ • Limit to 30    │                                                 │   │
│   │   └──────────────────┘         map_unit()                              │   │
│   │                                ┌──────────────────┐                    │   │
│   │                                │ UCUM → CloudWatch│                    │   │
│   │                                │ ms → Milliseconds│                    │   │
│   │                                │ By → Bytes       │                    │   │
│   │                                └──────────────────┘                    │   │
│   │                                                                        │   │
│   └────────────────────────────────────────────────────────────────────────┘   │
│                                       │                                        │
│                                       ▼                                        │
│   5. EMF DOCUMENT BUILDING                                                     │
│   ────────────────────────                                                     │
│                                                                                 │
│   ┌────────────────────────────────────────────────────────────────────────┐   │
│   │  {                                                                     │   │
│   │    "_aws": {                                                           │   │
│   │      "Timestamp": 1700000000000,                                       │   │
│   │      "LogGroupName": "/aws/...",     ◄── Optional                      │   │
│   │      "LogStreamName": "...",         ◄── Optional                      │   │
│   │      "CloudWatchMetrics": [{                                           │   │
│   │        "Namespace": "MyApp",                                           │   │
│   │        "Dimensions": [["dim1", "dim2"]],                               │   │
│   │        "Metrics": [{                                                   │   │
│   │          "Name": "metric_name",                                        │   │
│   │          "Unit": "Milliseconds",                                       │   │
│   │          "StorageResolution": 60                                       │   │
│   │        }]                                                              │   │
│   │      }]                                                                │   │
│   │    },                                                                  │   │
│   │    "metric_name": 42,                ◄── Metric value(s)               │   │
│   │    "dim1": "value1",                 ◄── Dimension values              │   │
│   │    "dim2": "value2"                                                    │   │
│   │  }                                                                     │   │
│   └────────────────────────────────────────────────────────────────────────┘   │
│                                       │                                        │
│                                       ▼                                        │
│   6. OUTPUT                                                                    │
│   ─────────                                                                    │
│                                                                                 │
│   ┌────────────────────────────────────────────────────────────────────────┐   │
│   │  _write_emf()                                                          │   │
│   │  ┌──────────────────────────────────────────────────────────────────┐  │   │
│   │  │  json.dumps(emf) ──► output.write() ──► output.flush()           │  │   │
│   │  └──────────────────────────────────────────────────────────────────┘  │   │
│   └────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### Core Components

| Component | File | Responsibility |
|-----------|------|----------------|
| `CloudWatchEMFExporter` | `exporter.py` | Main exporter class, implements MetricExporter interface |
| `map_unit` | `units.py` | Converts UCUM units to CloudWatch units |
| `_detect_aws_environment` | `exporter.py` | Detects Lambda/ECS/EC2 environment and selected ECS task metadata |
| `_sanitize_metric_name` | `exporter.py` | Ensures metric names are CloudWatch-compatible |

### Method Flow

```
export(metrics_data)
    │
    ├── for each ResourceMetrics
    │   │
    │   ├── Extract resource_attrs
    │   │
    │   └── for each Metric
    │       │
    │       └── _export_metric(metric, resource_attrs)
    │           │
    │           ├── Sum/Gauge ──► _export_number_metric()
    │           │                  │
    │           │                  └── _build_emf_document()
    │           │                      │
    │           │                      └── _write_emf()
    │           │
    │           ├── Histogram ──► _export_histogram_metric()
    │           │                  │
    │           │                  ├── histogram_as_values=True
    │           │                  │   └── _export_histogram_as_values()
    │           │                  │       └── _histogram_to_values_counts()
    │           │                  │           └── _expand_values_by_counts()
    │           │                  │
    │           │                  └── histogram_as_values=False
    │           │                      └── _export_histogram_as_derived()
    │           │
    │           └── ExponentialHistogram ──► _export_exponential_histogram_metric()
    │                                         │
    │                                         └── _exp_histogram_to_values_counts()
    │
    └── return SUCCESS/FAILURE
```

## Histogram Processing

### Values Array Mode (Default)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    HISTOGRAM TO VALUES CONVERSION                                │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   OTel Histogram Data Point                                                     │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │  explicit_bounds: [10, 50, 100, 200]                                    │   │
│   │  bucket_counts:   [10, 30,  40,  15, 5]                                 │   │
│   │                    ▲   ▲    ▲    ▲   ▲                                  │   │
│   │                    │   │    │    │   │                                  │   │
│   │         (-∞,10] (10,50] (50,100] (100,200] (200,+∞)                     │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                       │                                        │
│                                       ▼                                        │
│   Conversion Logic                                                              │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │  for each bucket with count > 0:                                        │   │
│   │      midpoint = (lower_bound + upper_bound) / 2                         │   │
│   │      repeat midpoint according to bucket_count                          │   │
│   │      proportionally sample output to EMF's 100-value array limit        │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                       │                                        │
│                                       ▼                                        │
│   EMF Output                                                                    │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │  {                                                                      │   │
│   │    "metric_name": [5, 5, 30, 30, 30, ...], ◄── count-weighted values    │   │
│   │    ...                                                                  │   │
│   │  }                                                                      │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│   CloudWatch can now calculate: Min, Max, Sum, Count, p50, p90, p99, etc.      │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Derived Metrics Mode

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    HISTOGRAM TO DERIVED METRICS                                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   OTel Histogram Data Point                                                     │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │  count: 100                                                             │   │
│   │  sum:   5000                                                            │   │
│   │  min:   10                                                              │   │
│   │  max:   200                                                             │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                       │                                        │
│                                       ▼                                        │
│   EMF Output (4 separate metrics)                                              │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │  {                                                                      │   │
│   │    "latency_count": 100,    Unit: Count                                 │   │
│   │    "latency_sum":   5000,   Unit: Milliseconds                          │   │
│   │    "latency_min":   10,     Unit: Milliseconds                          │   │
│   │    "latency_max":   200,    Unit: Milliseconds                          │   │
│   │    ...                                                                  │   │
│   │  }                                                                      │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│   Note: Percentiles NOT available in this mode                                  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Thread Safety

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           THREAD SAFETY MODEL                                    │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│   ┌─────────────────────────────────────────────────────────────────────────┐   │
│   │                        CloudWatchEMFExporter                            │   │
│   │                                                                         │   │
│   │   _lock: threading.Lock()                                               │   │
│   │      │                                                                  │   │
│   │      └── Protects: _shutdown flag                                       │   │
│   │                                                                         │   │
│   │   export()                                                              │   │
│   │   ┌─────────────────────────────────────────────────────────────────┐   │   │
│   │   │  with self._lock:                                               │   │   │
│   │   │      if self._shutdown:                                         │   │   │
│   │   │          return FAILURE                                         │   │   │
│   │   │                                                                 │   │   │
│   │   │  # Rest of export is lock-free                                  │   │   │
│   │   │  # (stateless processing)                                       │   │   │
│   │   └─────────────────────────────────────────────────────────────────┘   │   │
│   │                                                                         │   │
│   │   shutdown()                                                            │   │
│   │   ┌─────────────────────────────────────────────────────────────────┐   │   │
│   │   │  with self._lock:                                               │   │   │
│   │   │      self._shutdown = True                                      │   │   │
│   │   │                                                                 │   │   │
│   │   │  self.force_flush()                                             │   │   │
│   │   └─────────────────────────────────────────────────────────────────┘   │   │
│   │                                                                         │   │
│   └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│   Note: Output stream writes are not locked. If using a shared output           │
│   stream from multiple threads, provide a thread-safe stream.                   │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```
