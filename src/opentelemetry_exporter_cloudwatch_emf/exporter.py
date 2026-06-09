"""CloudWatch EMF Exporter for OpenTelemetry metrics.

Converts OpenTelemetry metrics to CloudWatch Embedded Metric Format (EMF) and
prints to stdout. CloudWatch Logs automatically parses EMF and creates metrics.
"""

from __future__ import annotations

import json
import logging
import math
import os
import sys
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, TextIO, Tuple
from urllib.error import URLError
from urllib.request import urlopen

from opentelemetry.sdk.metrics._internal.instrument import (
    Counter,
)
from opentelemetry.sdk.metrics._internal.instrument import Histogram as HistogramInstrument
from opentelemetry.sdk.metrics._internal.instrument import (
    ObservableCounter,
    ObservableGauge,
    ObservableUpDownCounter,
    UpDownCounter,
)
from opentelemetry.sdk.metrics._internal.point import Metric
from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    ExponentialHistogram,
    ExponentialHistogramDataPoint,
    Gauge,
    Histogram,
    HistogramDataPoint,
    MetricExporter,
    MetricExportResult,
    MetricsData,
    NumberDataPoint,
    Sum,
)

from opentelemetry_exporter_cloudwatch_emf.units import map_unit

logger = logging.getLogger(__name__)


def _detect_aws_environment() -> Dict[str, str]:
    """Detect AWS environment and return relevant attributes.

    Detects Lambda, ECS/Fargate, and EC2 environments.
    """
    env_attrs: Dict[str, str] = {}

    # Lambda detection
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        env_attrs["aws_lambda_function_name"] = os.environ["AWS_LAMBDA_FUNCTION_NAME"]
        if os.environ.get("AWS_LAMBDA_FUNCTION_VERSION"):
            env_attrs["aws_lambda_function_version"] = os.environ["AWS_LAMBDA_FUNCTION_VERSION"]
        if os.environ.get("AWS_REGION"):
            env_attrs["aws_region"] = os.environ["AWS_REGION"]
        if os.environ.get("AWS_LAMBDA_FUNCTION_MEMORY_SIZE"):
            env_attrs["aws_lambda_memory"] = os.environ["AWS_LAMBDA_FUNCTION_MEMORY_SIZE"]

    # ECS/Fargate detection
    elif os.environ.get("ECS_CONTAINER_METADATA_URI_V4") or os.environ.get(
        "ECS_CONTAINER_METADATA_URI"
    ):
        if os.environ.get("AWS_REGION"):
            env_attrs["aws_region"] = os.environ["AWS_REGION"]
        env_attrs["aws_ecs"] = "true"
        env_attrs.update(_detect_ecs_metadata())

    # EC2 detection (via IMDSv2 token presence or common env vars)
    elif os.environ.get("AWS_REGION"):
        env_attrs["aws_region"] = os.environ["AWS_REGION"]

    return env_attrs


def _detect_ecs_metadata(timeout: float = 0.2) -> Dict[str, str]:
    """Fetch selected ECS task/container metadata when available."""
    metadata_uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4") or os.environ.get(
        "ECS_CONTAINER_METADATA_URI"
    )
    if not metadata_uri:
        return {}

    attrs: Dict[str, str] = {}

    try:
        with urlopen(f"{metadata_uri}/task", timeout=timeout) as response:
            task_metadata = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, TimeoutError, ValueError):
        return attrs

    if not isinstance(task_metadata, Mapping):
        return attrs

    cluster = task_metadata.get("Cluster")
    if cluster:
        attrs["aws_ecs_cluster"] = str(cluster)

    task_arn = task_metadata.get("TaskARN")
    if task_arn:
        attrs["aws_ecs_task_arn"] = str(task_arn)

    family = task_metadata.get("Family")
    if family:
        attrs["aws_ecs_task_family"] = str(family)

    revision = task_metadata.get("Revision")
    if revision:
        attrs["aws_ecs_task_revision"] = str(revision)

    container_name = _ecs_container_name(task_metadata)
    if container_name:
        attrs["aws_ecs_container_name"] = container_name

    return attrs


def _ecs_container_name(task_metadata: Mapping[str, Any]) -> Optional[str]:
    """Return a stable container name from ECS task metadata."""
    containers = task_metadata.get("Containers")
    if not isinstance(containers, list):
        return None

    for container in containers:
        if not isinstance(container, Mapping):
            continue
        name = container.get("Name")
        if name:
            return str(name)

    return None


def _sanitize_metric_name(name: str) -> str:
    """Sanitize metric name for CloudWatch compatibility.

    CloudWatch metric names can contain:
    - Letters (a-z, A-Z)
    - Numbers (0-9)
    - Special characters: _ - / .

    Max length: 256 characters
    """
    # Replace common OTel separators
    sanitized = name.replace("::", "_").replace(":", "_")

    # Remove any invalid characters
    sanitized = "".join(c for c in sanitized if c.isalnum() or c in "_-/.")

    # Ensure it starts with a letter or number (CloudWatch requirement)
    if sanitized and not sanitized[0].isalnum():
        sanitized = "m" + sanitized

    return sanitized[:256]


class CloudWatchEMFExporter(MetricExporter):
    """OpenTelemetry metrics exporter using CloudWatch Embedded Metric Format.

    This exporter converts OpenTelemetry metrics to EMF JSON and prints them
    to stdout (or a custom output). When running in AWS environments,
    CloudWatch Logs automatically parses EMF and creates CloudWatch Metrics.

    Args:
        namespace: CloudWatch metrics namespace (required, 1-256 chars)
        output: Output stream for EMF JSON (default: sys.stdout)
        timestamp_fn: Function returning epoch milliseconds (default: current time)
        dimension_keys: List of resource/metric attribute keys to use as dimensions.
                       If None, uses all attributes (be careful of cardinality).
        max_dimensions: Maximum dimensions per metric (CloudWatch limit is 30)
        storage_resolution: 1 for high-resolution (sub-minute), 60 for standard
        log_group_name: Optional CloudWatch Log Group name for EMF routing
        log_stream_name: Optional CloudWatch Log Stream name for EMF routing
        auto_detect_aws: Whether to auto-detect AWS environment dimensions (default: True)
        histogram_as_values: Whether to emit histograms as Values/Counts arrays for
                            percentile support (default: True). If False, emits
                            _count/_sum/_min/_max metrics instead.

    Example:
        >>> exporter = CloudWatchEMFExporter(namespace="MyApp")
        >>> reader = PeriodicExportingMetricReader(exporter)
        >>> provider = MeterProvider(metric_readers=[reader])
    """

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
    ):
        if not namespace or len(namespace) > 256:
            raise ValueError("namespace must be 1-256 characters")
        if storage_resolution not in (1, 60):
            raise ValueError("storage_resolution must be 1 or 60")
        if max_dimensions < 0 or max_dimensions > 30:
            raise ValueError("max_dimensions must be 0-30")

        # EMF works best with delta temporality for counters
        preferred_temporality: Dict[type, AggregationTemporality] = {
            Counter: AggregationTemporality.DELTA,
            UpDownCounter: AggregationTemporality.DELTA,
            HistogramInstrument: AggregationTemporality.DELTA,
            ObservableCounter: AggregationTemporality.DELTA,
            ObservableUpDownCounter: AggregationTemporality.CUMULATIVE,
            ObservableGauge: AggregationTemporality.CUMULATIVE,
        }
        super().__init__(preferred_temporality=preferred_temporality)

        self._namespace = namespace
        self._output = output
        self._timestamp_fn = timestamp_fn or (lambda: int(time.time() * 1000))
        self._dimension_keys = dimension_keys
        self._max_dimensions = max_dimensions
        self._storage_resolution = storage_resolution
        self._log_group_name = log_group_name
        self._log_stream_name = log_stream_name
        self._histogram_as_values = histogram_as_values
        self._shutdown = False
        self._lock = threading.Lock()

        # Auto-detect AWS environment
        self._aws_env_attrs: Dict[str, str] = {}
        if auto_detect_aws:
            self._aws_env_attrs = _detect_aws_environment()
            if self._aws_env_attrs:
                logger.debug(f"Detected AWS environment: {self._aws_env_attrs}")

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10000,
        **kwargs: Any,
    ) -> MetricExportResult:
        """Export metrics as EMF JSON to stdout.

        Args:
            metrics_data: OpenTelemetry MetricsData containing metrics to export
            timeout_millis: Export timeout (unused, EMF export is synchronous)

        Returns:
            MetricExportResult.SUCCESS or MetricExportResult.FAILURE
        """
        with self._lock:
            if self._shutdown:
                logger.warning("Export called after shutdown")
                return MetricExportResult.FAILURE

        try:
            for resource_metrics in metrics_data.resource_metrics:
                resource_attrs = dict(resource_metrics.resource.attributes)

                for scope_metrics in resource_metrics.scope_metrics:
                    for metric in scope_metrics.metrics:
                        self._export_metric(metric, resource_attrs)

            return MetricExportResult.SUCCESS
        except Exception:
            logger.exception("Failed to export metrics")
            return MetricExportResult.FAILURE

    def _export_metric(
        self,
        metric: Metric,
        resource_attrs: Dict[str, Any],
    ) -> None:
        """Export a single metric as EMF JSON."""
        data = metric.data

        if isinstance(data, (Sum, Gauge)):
            self._export_number_metric(metric, data.data_points, resource_attrs)
        elif isinstance(data, Histogram):
            self._export_histogram_metric(metric, data.data_points, resource_attrs)
        elif isinstance(data, ExponentialHistogram):
            self._export_exponential_histogram_metric(metric, data.data_points, resource_attrs)

    def _export_number_metric(
        self,
        metric: Metric,
        data_points: Sequence[NumberDataPoint],
        resource_attrs: Dict[str, Any],
    ) -> None:
        """Export counter/gauge metrics."""
        for point in data_points:
            dimensions = self._build_dimensions(point.attributes, resource_attrs)
            value = point.value
            metric_name = _sanitize_metric_name(metric.name)

            if not self._is_valid_emf_number(value):
                logger.warning("Skipping non-finite metric value for %s", metric_name)
                continue

            emf = self._build_emf_document(
                metric_name=metric_name,
                metric_value=value,
                metric_unit=metric.unit,
                dimensions=dimensions,
            )
            self._write_emf(emf)

    def _export_histogram_metric(
        self,
        metric: Metric,
        data_points: Sequence[HistogramDataPoint],
        resource_attrs: Dict[str, Any],
    ) -> None:
        """Export histogram metrics.

        If histogram_as_values is True (default), emits histogram data as
        Values/Counts arrays which enable percentile calculations in CloudWatch.

        If histogram_as_values is False, emits derived metrics:
        - {name}_count: Number of observations
        - {name}_sum: Sum of all observations
        - {name}_min: Minimum value
        - {name}_max: Maximum value
        """
        for point in data_points:
            dimensions = self._build_dimensions(point.attributes, resource_attrs)
            metric_name = _sanitize_metric_name(metric.name)

            if self._histogram_as_values:
                self._export_histogram_as_values(metric_name, metric.unit, point, dimensions)
            else:
                self._export_histogram_as_derived(metric_name, metric.unit, point, dimensions)

    def _export_histogram_as_values(
        self,
        metric_name: str,
        metric_unit: Optional[str],
        point: HistogramDataPoint,
        dimensions: Dict[str, str],
    ) -> None:
        """Export histogram using Values/Counts arrays for percentile support."""
        values, counts = self._histogram_to_values_counts(point)
        metric_values = self._expand_values_by_counts(values, counts)

        if not metric_values:
            return

        cw_unit = map_unit(metric_unit)
        dimensions = self._filter_metric_name_collisions(dimensions, [metric_name])
        dimension_keys = list(dimensions.keys())

        emf: Dict[str, Any] = {
            "_aws": {
                "Timestamp": self._timestamp_fn(),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self._namespace,
                        "Dimensions": [dimension_keys] if dimension_keys else [[]],
                        "Metrics": [
                            {
                                "Name": metric_name,
                                "Unit": cw_unit,
                                "StorageResolution": self._storage_resolution,
                            }
                        ],
                    }
                ],
            },
            metric_name: metric_values if len(metric_values) > 1 else metric_values[0],
        }

        # Add log group/stream if configured
        self._add_log_routing(emf)

        # Add dimensions as top-level keys
        emf.update(dimensions)

        self._write_emf(emf)

    def _histogram_to_values_counts(
        self, point: HistogramDataPoint
    ) -> Tuple[List[float], List[int]]:
        """Convert histogram buckets to Values/Counts arrays.

        Uses bucket midpoints as representative values for each bucket.
        """
        values: List[float] = []
        counts: List[int] = []

        if not point.bucket_counts or not point.explicit_bounds:
            # No bucket data, use min/max/sum if available
            if (
                point.min is not None
                and point.max is not None
                and self._is_valid_emf_number(point.min)
                and self._is_valid_emf_number(point.max)
                and point.count
                and point.count > 0
            ):
                # Use min and max as representative values
                if point.min == point.max:
                    values.append(point.min)
                    counts.append(point.count)
                else:
                    # Distribute count between min and max
                    values.append(point.min)
                    values.append(point.max)
                    counts.append(point.count // 2)
                    counts.append(point.count - point.count // 2)
            return values, counts

        bounds = list(point.explicit_bounds)
        bucket_counts = list(point.bucket_counts)

        # Process each bucket
        for i, count in enumerate(bucket_counts):
            if count == 0:
                continue

            # Calculate bucket midpoint
            if i == 0:
                # First bucket: (-inf, bounds[0])
                if bounds:
                    midpoint = bounds[0] / 2 if bounds[0] > 0 else bounds[0] - 1
                else:
                    continue
            elif i == len(bounds):
                # Last bucket: (bounds[-1], +inf)
                midpoint = bounds[-1] * 1.5 if bounds[-1] > 0 else bounds[-1] + 1
            else:
                # Middle bucket: (bounds[i-1], bounds[i])
                midpoint = (bounds[i - 1] + bounds[i]) / 2

            if not self._is_valid_emf_number(midpoint):
                continue

            values.append(midpoint)
            counts.append(count)

        return values, counts

    def _export_histogram_as_derived(
        self,
        metric_name: str,
        metric_unit: Optional[str],
        point: HistogramDataPoint,
        dimensions: Dict[str, str],
    ) -> None:
        """Export histogram as derived _count/_sum/_min/_max metrics."""
        metrics_list = []
        values: Dict[str, float] = {}

        if point.count is not None and self._is_valid_emf_number(point.count) and point.count > 0:
            metrics_list.append({"Name": f"{metric_name}_count", "Unit": "Count"})
            values[f"{metric_name}_count"] = point.count

        if point.sum is not None and self._is_valid_emf_number(point.sum):
            unit = map_unit(metric_unit)
            metrics_list.append({"Name": f"{metric_name}_sum", "Unit": unit})
            values[f"{metric_name}_sum"] = point.sum

        if point.min is not None and self._is_valid_emf_number(point.min):
            unit = map_unit(metric_unit)
            metrics_list.append({"Name": f"{metric_name}_min", "Unit": unit})
            values[f"{metric_name}_min"] = point.min

        if point.max is not None and self._is_valid_emf_number(point.max):
            unit = map_unit(metric_unit)
            metrics_list.append({"Name": f"{metric_name}_max", "Unit": unit})
            values[f"{metric_name}_max"] = point.max

        if metrics_list:
            emf = self._build_emf_document_multi(
                metrics=metrics_list,
                values=values,
                dimensions=dimensions,
            )
            self._write_emf(emf)

    def _export_exponential_histogram_metric(
        self,
        metric: Metric,
        data_points: Sequence[ExponentialHistogramDataPoint],
        resource_attrs: Dict[str, Any],
    ) -> None:
        """Export exponential histogram metrics.

        Exponential histograms use a base-2 exponential scale for bucket boundaries,
        providing efficient representation of distributions.
        """
        for point in data_points:
            dimensions = self._build_dimensions(point.attributes, resource_attrs)
            metric_name = _sanitize_metric_name(metric.name)

            if self._histogram_as_values:
                values, counts = self._exp_histogram_to_values_counts(point)
                if values:
                    self._emit_values_metric(metric_name, metric.unit, values, dimensions, counts)
            else:
                # Fall back to derived metrics
                self._export_exp_histogram_as_derived(metric_name, metric.unit, point, dimensions)

    def _exp_histogram_to_values_counts(
        self, point: ExponentialHistogramDataPoint
    ) -> Tuple[List[float], List[int]]:
        """Convert exponential histogram to Values/Counts arrays."""
        values: List[float] = []
        counts: List[int] = []

        scale = point.scale
        base = 2 ** (2 ** (-scale))

        # Process positive buckets
        if point.positive and point.positive.bucket_counts:
            offset = point.positive.offset
            for i, count in enumerate(point.positive.bucket_counts):
                if count == 0:
                    continue
                # Calculate bucket midpoint using exponential scale
                lower = base ** (offset + i)
                upper = base ** (offset + i + 1)
                midpoint = (lower + upper) / 2
                values.append(midpoint)
                counts.append(count)

        # Process negative buckets
        if point.negative and point.negative.bucket_counts:
            offset = point.negative.offset
            for i, count in enumerate(point.negative.bucket_counts):
                if count == 0:
                    continue
                lower = -(base ** (offset + i + 1))
                upper = -(base ** (offset + i))
                midpoint = (lower + upper) / 2
                values.append(midpoint)
                counts.append(count)

        # Process zero count
        if point.zero_count and point.zero_count > 0:
            values.append(0.0)
            counts.append(point.zero_count)

        return values, counts

    def _expand_values_by_counts(
        self,
        values: Sequence[float],
        counts: Sequence[int],
        max_values: int = 100,
    ) -> List[float]:
        """Expand bucket representatives into an EMF numeric array.

        EMF has no separate Counts field; numeric metric arrays are capped at
        100 values. For larger histograms, keep one sample per bucket where
        possible and distribute the remaining samples proportionally.
        """
        weighted = [(float(value), int(count)) for value, count in zip(values, counts) if count > 0]
        if not weighted or max_values <= 0:
            return []

        total_count = sum(count for _, count in weighted)
        if total_count <= max_values:
            expanded: List[float] = []
            for value, count in weighted:
                expanded.extend([value] * count)
            return expanded

        if len(weighted) >= max_values:
            return self._sample_weighted_values(weighted, max_values)

        remaining_slots = max_values - len(weighted)
        if remaining_slots <= 0:
            return [value for value, _ in weighted]

        allocations: List[Tuple[float, int, float]] = []
        allocated = len(weighted)
        for value, count in weighted:
            exact_extra = (count / total_count) * remaining_slots
            extra = int(exact_extra)
            allocations.append((value, 1 + extra, exact_extra - extra))
            allocated += extra

        extras_by_index: Dict[int, int] = {}
        ranked_allocations = sorted(
            enumerate(allocations),
            key=lambda item: item[1][2],
            reverse=True,
        )
        for index, _ in ranked_allocations:
            if allocated >= max_values:
                break
            extras_by_index[index] = extras_by_index.get(index, 0) + 1
            allocated += 1

        expanded = []
        for index, (value, count, _) in enumerate(allocations):
            expanded.extend([value] * (count + extras_by_index.get(index, 0)))
        return expanded[:max_values]

    def _sample_weighted_values(
        self,
        weighted: Sequence[Tuple[float, int]],
        max_values: int,
    ) -> List[float]:
        """Sample weighted bucket representatives across the full distribution."""
        total_count = sum(count for _, count in weighted)
        if total_count <= 0:
            return []

        sampled: List[float] = []
        bucket_index = 0
        cumulative = weighted[0][1]

        for sample_index in range(max_values):
            rank = ((sample_index + 0.5) * total_count) / max_values
            while bucket_index < len(weighted) - 1 and cumulative < rank:
                bucket_index += 1
                cumulative += weighted[bucket_index][1]
            sampled.append(weighted[bucket_index][0])

        return sampled

    def _export_exp_histogram_as_derived(
        self,
        metric_name: str,
        metric_unit: Optional[str],
        point: ExponentialHistogramDataPoint,
        dimensions: Dict[str, str],
    ) -> None:
        """Export exponential histogram as derived metrics."""
        metrics_list = []
        values: Dict[str, float] = {}

        if point.count is not None and point.count > 0:
            metrics_list.append({"Name": f"{metric_name}_count", "Unit": "Count"})
            values[f"{metric_name}_count"] = point.count

        if point.sum is not None:
            unit = map_unit(metric_unit)
            metrics_list.append({"Name": f"{metric_name}_sum", "Unit": unit})
            values[f"{metric_name}_sum"] = point.sum

        if point.min is not None:
            unit = map_unit(metric_unit)
            metrics_list.append({"Name": f"{metric_name}_min", "Unit": unit})
            values[f"{metric_name}_min"] = point.min

        if point.max is not None:
            unit = map_unit(metric_unit)
            metrics_list.append({"Name": f"{metric_name}_max", "Unit": unit})
            values[f"{metric_name}_max"] = point.max

        if metrics_list:
            emf = self._build_emf_document_multi(
                metrics=metrics_list,
                values=values,
                dimensions=dimensions,
            )
            self._write_emf(emf)

    def _emit_values_metric(
        self,
        metric_name: str,
        metric_unit: Optional[str],
        values: List[float],
        dimensions: Dict[str, str],
        counts: Optional[List[int]] = None,
    ) -> None:
        """Emit a metric with multiple values."""
        metric_values = self._expand_values_by_counts(values, counts or [1] * len(values))
        if not metric_values:
            return

        cw_unit = map_unit(metric_unit)
        dimension_keys = list(dimensions.keys())

        emf: Dict[str, Any] = {
            "_aws": {
                "Timestamp": self._timestamp_fn(),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self._namespace,
                        "Dimensions": [dimension_keys] if dimension_keys else [[]],
                        "Metrics": [
                            {
                                "Name": metric_name,
                                "Unit": cw_unit,
                                "StorageResolution": self._storage_resolution,
                            }
                        ],
                    }
                ],
            },
            metric_name: metric_values if len(metric_values) > 1 else metric_values[0],
        }

        self._add_log_routing(emf)
        emf.update(dimensions)
        self._write_emf(emf)

    def _build_dimensions(
        self,
        point_attrs: Optional[Mapping[str, Any]],
        resource_attrs: Dict[str, Any],
    ) -> Dict[str, str]:
        """Build dimensions from point and resource attributes."""
        point_attr_dict = dict(point_attrs) if point_attrs else {}
        attr_sources: List[Mapping[str, Any]] = [
            point_attr_dict,
            resource_attrs,
            self._aws_env_attrs,
        ]

        if self._dimension_keys:
            filtered = {}
            for key in self._dimension_keys:
                for source in attr_sources:
                    if key in source:
                        filtered[key] = source[key]
                        break
        else:
            filtered = {}
            for source in attr_sources:
                for key, value in source.items():
                    if key not in filtered:
                        filtered[key] = value

        # Convert to strings and limit count
        dimensions: Dict[str, str] = {}
        for key, value in list(filtered.items())[: self._max_dimensions]:
            # CloudWatch dimension values must be strings, max 1024 chars
            str_value = str(value)[:1024]
            # CloudWatch dimension names must be valid
            safe_key = self._sanitize_dimension_name(key)
            if safe_key and str_value:
                dimensions[safe_key] = str_value

        return dimensions

    def _sanitize_dimension_name(self, name: str) -> str:
        """Sanitize dimension name for CloudWatch compatibility."""
        # Replace dots and slashes with underscores (common in OTel attributes)
        sanitized = name.replace(".", "_").replace("/", "_")
        # Remove any remaining invalid characters
        sanitized = "".join(c for c in sanitized if c.isalnum() or c in "_-")
        return sanitized[:250]  # CloudWatch limit

    def _add_log_routing(self, emf: Dict[str, Any]) -> None:
        """Add log group/stream to EMF metadata if configured."""
        if self._log_group_name or self._log_stream_name:
            if self._log_group_name:
                emf["_aws"]["LogGroupName"] = self._log_group_name
            if self._log_stream_name:
                emf["_aws"]["LogStreamName"] = self._log_stream_name

    def _build_emf_document(
        self,
        metric_name: str,
        metric_value: float,
        metric_unit: Optional[str],
        dimensions: Dict[str, str],
    ) -> Dict[str, Any]:
        """Build a single-metric EMF document."""
        cw_unit = map_unit(metric_unit)
        dimensions = self._filter_metric_name_collisions(dimensions, [metric_name])
        dimension_keys = list(dimensions.keys())

        emf: Dict[str, Any] = {
            "_aws": {
                "Timestamp": self._timestamp_fn(),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self._namespace,
                        "Dimensions": [dimension_keys] if dimension_keys else [[]],
                        "Metrics": [
                            {
                                "Name": metric_name,
                                "Unit": cw_unit,
                                "StorageResolution": self._storage_resolution,
                            }
                        ],
                    }
                ],
            },
            metric_name: metric_value,
        }

        # Add log group/stream if configured
        self._add_log_routing(emf)

        # Add dimensions as top-level keys
        emf.update(dimensions)

        return emf

    def _build_emf_document_multi(
        self,
        metrics: List[Dict[str, Any]],
        values: Dict[str, float],
        dimensions: Dict[str, str],
    ) -> Dict[str, Any]:
        """Build an EMF document with multiple metrics (for histograms)."""
        dimensions = self._filter_metric_name_collisions(dimensions, values.keys())
        dimension_keys = list(dimensions.keys())

        # Add storage resolution to each metric
        for m in metrics:
            m["StorageResolution"] = self._storage_resolution

        emf: Dict[str, Any] = {
            "_aws": {
                "Timestamp": self._timestamp_fn(),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self._namespace,
                        "Dimensions": [dimension_keys] if dimension_keys else [[]],
                        "Metrics": metrics,
                    }
                ],
            },
        }

        # Add log group/stream if configured
        self._add_log_routing(emf)

        # Add metric values as top-level keys
        emf.update(values)
        # Add dimensions as top-level keys
        emf.update(dimensions)

        return emf

    def _write_emf(self, emf: Dict[str, Any]) -> None:
        """Write EMF document to output."""
        line = json.dumps(emf, separators=(",", ":"), allow_nan=False)
        self._output.write(line + "\n")
        self._output.flush()

    def _is_valid_emf_number(self, value: Any) -> bool:
        """Return True when value can be emitted as a valid JSON number."""
        return isinstance(value, (int, float)) and math.isfinite(value)

    def _filter_metric_name_collisions(
        self,
        dimensions: Dict[str, str],
        metric_names: Iterable[str],
    ) -> Dict[str, str]:
        """Drop dimensions that would overwrite metric values in the EMF document."""
        metric_name_set = set(metric_names)
        return {key: value for key, value in dimensions.items() if key not in metric_name_set}

    def force_flush(self, timeout_millis: float = 10000) -> bool:
        """Flush any buffered data.

        EMF export is synchronous, so this just flushes the output stream.
        """
        try:
            self._output.flush()
            return True
        except Exception:
            return False

    def shutdown(self, timeout_millis: float = 30000, **kwargs: Any) -> None:
        """Shutdown the exporter."""
        with self._lock:
            self._shutdown = True
        self.force_flush()
        logger.debug("CloudWatch EMF Exporter shut down")
