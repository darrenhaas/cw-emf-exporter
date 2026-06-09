"""Tests for CloudWatch EMF Exporter."""

import io
import json
import math
import os
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from opentelemetry_exporter_cloudwatch_emf import CloudWatchEMFExporter
from opentelemetry_exporter_cloudwatch_emf.exporter import (
    _detect_aws_environment,
    _sanitize_metric_name,
)
from opentelemetry_exporter_cloudwatch_emf.units import map_unit


class TestUnitMapping:
    """Test unit mapping from OpenTelemetry to CloudWatch."""

    def test_time_units(self):
        assert map_unit("s") == "Seconds"
        assert map_unit("ms") == "Milliseconds"
        assert map_unit("us") == "Microseconds"

    def test_byte_units(self):
        assert map_unit("By") == "Bytes"
        assert map_unit("KBy") == "Kilobytes"
        assert map_unit("KiBy") == "Kilobytes"
        assert map_unit("MBy") == "Megabytes"
        assert map_unit("MiBy") == "Megabytes"
        assert map_unit("GBy") == "Gigabytes"
        assert map_unit("GiBy") == "Gigabytes"
        assert map_unit("TBy") == "Terabytes"

    def test_count_units(self):
        assert map_unit("1") == "Count"
        assert map_unit("{request}") == "Count"
        assert map_unit("{requests}") == "Count"
        assert map_unit("{error}") == "Count"
        assert map_unit("{errors}") == "Count"
        assert map_unit("{operation}") == "Count"

    def test_percent_unit(self):
        assert map_unit("%") == "Percent"

    def test_unknown_unit(self):
        assert map_unit("unknown") == "None"
        assert map_unit("foobar") == "None"

    def test_none_unit(self):
        assert map_unit(None) == "None"
        assert map_unit("") == "None"


class TestMetricNameSanitization:
    """Test metric name sanitization."""

    def test_valid_name_unchanged(self):
        assert _sanitize_metric_name("request_count") == "request_count"
        assert _sanitize_metric_name("http.requests") == "http.requests"

    def test_double_colon_replaced(self):
        assert _sanitize_metric_name("aws::lambda::invocations") == "aws_lambda_invocations"

    def test_invalid_chars_removed(self):
        assert _sanitize_metric_name("metric@name#test") == "metricnametest"

    def test_length_truncated(self):
        long_name = "x" * 300
        result = _sanitize_metric_name(long_name)
        assert len(result) == 256

    def test_leading_non_alnum_fixed(self):
        assert _sanitize_metric_name("_metric") == "m_metric"
        assert _sanitize_metric_name("-metric") == "m-metric"


class TestAWSEnvironmentDetection:
    """Test AWS environment auto-detection."""

    def test_lambda_detection(self):
        env = {
            "AWS_LAMBDA_FUNCTION_NAME": "my-function",
            "AWS_LAMBDA_FUNCTION_VERSION": "$LATEST",
            "AWS_REGION": "us-east-1",
            "AWS_LAMBDA_FUNCTION_MEMORY_SIZE": "512",
        }
        with patch.dict(os.environ, env, clear=True):
            attrs = _detect_aws_environment()
            assert attrs["aws_lambda_function_name"] == "my-function"
            assert attrs["aws_lambda_function_version"] == "$LATEST"
            assert attrs["aws_region"] == "us-east-1"
            assert attrs["aws_lambda_memory"] == "512"

    def test_ecs_detection(self):
        env = {
            "ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/...",
            "AWS_REGION": "us-west-2",
        }
        with patch.dict(os.environ, env, clear=True):
            attrs = _detect_aws_environment()
            assert attrs["aws_ecs"] == "true"
            assert attrs["aws_region"] == "us-west-2"

    def test_ecs_metadata_detection(self):
        env = {
            "ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/abc",
            "AWS_REGION": "us-west-2",
        }
        task_metadata = {
            "Cluster": "arn:aws:ecs:us-west-2:123456789012:cluster/prod",
            "TaskARN": "arn:aws:ecs:us-west-2:123456789012:task/prod/abc",
            "Family": "api",
            "Revision": "17",
            "Containers": [{"Name": "api-container"}],
        }
        response = MagicMock()
        response.read.return_value = json.dumps(task_metadata).encode("utf-8")
        response.__enter__.return_value = response

        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "opentelemetry_exporter_cloudwatch_emf.exporter.urlopen",
                return_value=response,
            ) as mock_urlopen,
        ):
            attrs = _detect_aws_environment()

        mock_urlopen.assert_called_once_with("http://169.254.170.2/v4/abc/task", timeout=0.2)
        assert attrs["aws_ecs"] == "true"
        assert attrs["aws_region"] == "us-west-2"
        assert attrs["aws_ecs_cluster"] == task_metadata["Cluster"]
        assert attrs["aws_ecs_task_arn"] == task_metadata["TaskARN"]
        assert attrs["aws_ecs_task_family"] == "api"
        assert attrs["aws_ecs_task_revision"] == "17"
        assert attrs["aws_ecs_container_name"] == "api-container"

    def test_ecs_metadata_detection_ignores_failures(self):
        env = {
            "ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/abc",
            "AWS_REGION": "us-west-2",
        }

        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "opentelemetry_exporter_cloudwatch_emf.exporter.urlopen",
                side_effect=TimeoutError,
            ),
        ):
            attrs = _detect_aws_environment()

        assert attrs == {"aws_region": "us-west-2", "aws_ecs": "true"}

    def test_ecs_metadata_detection_ignores_non_object_payload(self):
        env = {
            "ECS_CONTAINER_METADATA_URI_V4": "http://169.254.170.2/v4/abc",
            "AWS_REGION": "us-west-2",
        }
        response = MagicMock()
        response.read.return_value = b"[]"
        response.__enter__.return_value = response

        with (
            patch.dict(os.environ, env, clear=True),
            patch(
                "opentelemetry_exporter_cloudwatch_emf.exporter.urlopen",
                return_value=response,
            ),
        ):
            attrs = _detect_aws_environment()

        assert attrs == {"aws_region": "us-west-2", "aws_ecs": "true"}

    def test_no_aws_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            attrs = _detect_aws_environment()
            assert attrs == {}


class TestCloudWatchEMFExporter:
    """Test CloudWatch EMF Exporter initialization."""

    def test_init_valid_namespace(self):
        exporter = CloudWatchEMFExporter(namespace="MyApp", auto_detect_aws=False)
        assert exporter._namespace == "MyApp"

    def test_init_empty_namespace_raises(self):
        with pytest.raises(ValueError, match="namespace must be 1-256"):
            CloudWatchEMFExporter(namespace="")

    def test_init_long_namespace_raises(self):
        with pytest.raises(ValueError, match="namespace must be 1-256"):
            CloudWatchEMFExporter(namespace="x" * 257)

    def test_init_invalid_storage_resolution_raises(self):
        with pytest.raises(ValueError, match="storage_resolution must be 1 or 60"):
            CloudWatchEMFExporter(namespace="MyApp", storage_resolution=30)

    def test_init_invalid_max_dimensions_raises(self):
        with pytest.raises(ValueError, match="max_dimensions must be 0-30"):
            CloudWatchEMFExporter(namespace="MyApp", max_dimensions=31)

    def test_custom_output_stream(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(namespace="MyApp", output=output, auto_detect_aws=False)
        assert exporter._output is output

    def test_custom_timestamp_fn(self):
        exporter = CloudWatchEMFExporter(
            namespace="MyApp",
            timestamp_fn=lambda: 1234567890000,
            auto_detect_aws=False,
        )
        assert exporter._timestamp_fn() == 1234567890000

    def test_log_group_stream_config(self):
        exporter = CloudWatchEMFExporter(
            namespace="MyApp",
            log_group_name="/aws/lambda/my-function",
            log_stream_name="2024/01/01/[$LATEST]abc123",
            auto_detect_aws=False,
        )
        assert exporter._log_group_name == "/aws/lambda/my-function"
        assert exporter._log_stream_name == "2024/01/01/[$LATEST]abc123"


class TestLogGroupStreamRouting:
    """Test log group/stream EMF routing."""

    def test_log_group_added_to_emf(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            log_group_name="/aws/lambda/test",
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )

        emf = exporter._build_emf_document(
            metric_name="test",
            metric_value=1,
            metric_unit="1",
            dimensions={},
        )

        assert emf["_aws"]["LogGroupName"] == "/aws/lambda/test"

    def test_log_stream_added_to_emf(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            log_group_name="/aws/lambda/test",
            log_stream_name="stream123",
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )

        emf = exporter._build_emf_document(
            metric_name="test",
            metric_value=1,
            metric_unit="1",
            dimensions={},
        )

        assert emf["_aws"]["LogGroupName"] == "/aws/lambda/test"
        assert emf["_aws"]["LogStreamName"] == "stream123"


class TestEMFDocumentGeneration:
    """Test EMF document structure."""

    def create_exporter(self, output: io.StringIO) -> CloudWatchEMFExporter:
        return CloudWatchEMFExporter(
            namespace="TestNamespace",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )

    def test_build_emf_document_structure(self):
        output = io.StringIO()
        exporter = self.create_exporter(output)

        emf = exporter._build_emf_document(
            metric_name="request_count",
            metric_value=42,
            metric_unit="1",
            dimensions={"service": "api", "environment": "prod"},
        )

        # Check _aws metadata
        assert "_aws" in emf
        assert emf["_aws"]["Timestamp"] == 1700000000000
        assert "CloudWatchMetrics" in emf["_aws"]

        # Check metrics definition
        cw_metrics = emf["_aws"]["CloudWatchMetrics"][0]
        assert cw_metrics["Namespace"] == "TestNamespace"
        assert cw_metrics["Dimensions"] == [["service", "environment"]]
        assert cw_metrics["Metrics"][0]["Name"] == "request_count"
        assert cw_metrics["Metrics"][0]["Unit"] == "Count"

        # Check values at root
        assert emf["request_count"] == 42
        assert emf["service"] == "api"
        assert emf["environment"] == "prod"

    def test_build_emf_document_no_dimensions(self):
        output = io.StringIO()
        exporter = self.create_exporter(output)

        emf = exporter._build_emf_document(
            metric_name="total_requests",
            metric_value=100,
            metric_unit="1",
            dimensions={},
        )

        cw_metrics = emf["_aws"]["CloudWatchMetrics"][0]
        assert cw_metrics["Dimensions"] == [[]]

    def test_storage_resolution_high(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestNamespace",
            output=output,
            storage_resolution=1,
            auto_detect_aws=False,
        )

        emf = exporter._build_emf_document(
            metric_name="latency",
            metric_value=50,
            metric_unit="ms",
            dimensions={},
        )

        metrics = emf["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]
        assert metrics["StorageResolution"] == 1

    def test_metric_name_dimension_collision_drops_dimension(self):
        output = io.StringIO()
        exporter = self.create_exporter(output)

        emf = exporter._build_emf_document(
            metric_name="latency",
            metric_value=50,
            metric_unit="ms",
            dimensions={"latency": "dimension-value", "service": "api"},
        )

        cw_metrics = emf["_aws"]["CloudWatchMetrics"][0]
        assert cw_metrics["Dimensions"] == [["service"]]
        assert emf["latency"] == 50
        assert emf["service"] == "api"


class TestDimensionHandling:
    """Test dimension building and sanitization."""

    def test_sanitize_dimension_name_dots(self):
        exporter = CloudWatchEMFExporter(namespace="Test", auto_detect_aws=False)
        assert exporter._sanitize_dimension_name("service.name") == "service_name"

    def test_sanitize_dimension_name_slashes(self):
        exporter = CloudWatchEMFExporter(namespace="Test", auto_detect_aws=False)
        assert exporter._sanitize_dimension_name("http/method") == "http_method"

    def test_sanitize_dimension_name_special_chars(self):
        exporter = CloudWatchEMFExporter(namespace="Test", auto_detect_aws=False)
        assert exporter._sanitize_dimension_name("foo@bar#baz") == "foobarbaz"

    def test_sanitize_dimension_name_length_limit(self):
        exporter = CloudWatchEMFExporter(namespace="Test", auto_detect_aws=False)
        long_name = "x" * 300
        sanitized = exporter._sanitize_dimension_name(long_name)
        assert len(sanitized) == 250

    def test_dimension_keys_filter(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="Test",
            output=output,
            dimension_keys=["service", "environment"],
            auto_detect_aws=False,
        )

        dimensions = exporter._build_dimensions(
            point_attrs={"service": "api", "host": "server1", "region": "us-west-2"},
            resource_attrs={"environment": "prod"},
        )

        assert dimensions == {"service": "api", "environment": "prod"}
        assert "host" not in dimensions
        assert "region" not in dimensions

    def test_max_dimensions_limit(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="Test",
            output=output,
            max_dimensions=2,
            auto_detect_aws=False,
        )

        dimensions = exporter._build_dimensions(
            point_attrs={"a": "1", "b": "2", "c": "3", "d": "4"},
            resource_attrs={},
        )

        assert len(dimensions) == 2

    def test_max_dimensions_prefers_point_attributes(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="Test",
            output=output,
            max_dimensions=2,
            auto_detect_aws=False,
        )
        exporter._aws_env_attrs = {"aws_region": "us-west-2"}

        dimensions = exporter._build_dimensions(
            point_attrs={"operation": "checkout", "status": "ok"},
            resource_attrs={"service": "api"},
        )

        assert dimensions == {"operation": "checkout", "status": "ok"}


class TestExportFlow:
    """Test the export method with mock metrics data."""

    def create_mock_metrics_data(
        self,
        metric_name: str = "test_metric",
        metric_value: float = 1.0,
        metric_unit: str = "1",
        attributes: Dict[str, Any] = None,
    ) -> MagicMock:
        """Create a mock MetricsData structure."""
        if attributes is None:
            attributes = {}

        # Create mock data point
        data_point = MagicMock()
        data_point.value = metric_value
        data_point.attributes = attributes

        # Create mock Sum data
        sum_data = MagicMock()
        sum_data.data_points = [data_point]

        # Create mock metric
        metric = MagicMock()
        metric.name = metric_name
        metric.unit = metric_unit
        metric.data = sum_data

        # Make data look like Sum type
        from opentelemetry.sdk.metrics.export import Sum

        metric.data.__class__ = Sum

        # Create mock scope metrics
        scope_metrics = MagicMock()
        scope_metrics.metrics = [metric]

        # Create mock resource
        resource = MagicMock()
        resource.attributes = {"service.name": "test-service"}

        # Create mock resource metrics
        resource_metrics = MagicMock()
        resource_metrics.resource = resource
        resource_metrics.scope_metrics = [scope_metrics]

        # Create mock metrics data
        metrics_data = MagicMock()
        metrics_data.resource_metrics = [resource_metrics]

        return metrics_data

    def test_export_writes_emf_json(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_metrics_data(
            metric_name="request_count",
            metric_value=42,
            attributes={"endpoint": "/api"},
        )

        from opentelemetry.sdk.metrics.export import MetricExportResult

        result = exporter.export(metrics_data)

        assert result == MetricExportResult.SUCCESS

        output.seek(0)
        line = output.readline()
        emf = json.loads(line)

        assert emf["_aws"]["Timestamp"] == 1700000000000
        assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "TestApp"
        assert emf["request_count"] == 42

    @pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
    def test_export_skips_non_finite_metric_values(self, value: float):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_metrics_data(
            metric_name="temperature",
            metric_value=value,
        )

        from opentelemetry.sdk.metrics.export import MetricExportResult

        result = exporter.export(metrics_data)

        assert result == MetricExportResult.SUCCESS
        assert output.getvalue() == ""

    def test_export_after_shutdown_fails(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(namespace="Test", output=output, auto_detect_aws=False)
        exporter.shutdown()

        metrics_data = self.create_mock_metrics_data()

        from opentelemetry.sdk.metrics.export import MetricExportResult

        result = exporter.export(metrics_data)
        assert result == MetricExportResult.FAILURE

    def test_export_write_failure_returns_failure(self):
        class BrokenOutput:
            def write(self, value: str) -> None:
                raise RuntimeError("write failed")

            def flush(self) -> None:
                pass

        exporter = CloudWatchEMFExporter(
            namespace="Test",
            output=BrokenOutput(),
            auto_detect_aws=False,
        )
        metrics_data = self.create_mock_metrics_data()

        from opentelemetry.sdk.metrics.export import MetricExportResult

        result = exporter.export(metrics_data)

        assert result == MetricExportResult.FAILURE


class TestHistogramExportDerived:
    """Test histogram export with derived metrics (_count/_sum/_min/_max)."""

    def create_mock_histogram_data(
        self,
        metric_name: str = "latency",
        metric_unit: str = "ms",
        count: int = 100,
        sum_value: float = 5000.0,
        min_value: float = 10.0,
        max_value: float = 200.0,
        attributes: Dict[str, Any] = None,
        bucket_counts: list = None,
        explicit_bounds: list = None,
    ) -> MagicMock:
        """Create a mock MetricsData with histogram data."""
        if attributes is None:
            attributes = {}

        # Create mock histogram data point
        data_point = MagicMock()
        data_point.count = count
        data_point.sum = sum_value
        data_point.min = min_value
        data_point.max = max_value
        data_point.attributes = attributes
        data_point.bucket_counts = bucket_counts
        data_point.explicit_bounds = explicit_bounds

        # Create mock Histogram data
        histogram_data = MagicMock()
        histogram_data.data_points = [data_point]

        # Create mock metric
        metric = MagicMock()
        metric.name = metric_name
        metric.unit = metric_unit
        metric.data = histogram_data

        # Make data look like Histogram type
        from opentelemetry.sdk.metrics.export import Histogram

        metric.data.__class__ = Histogram

        # Create mock scope metrics
        scope_metrics = MagicMock()
        scope_metrics.metrics = [metric]

        # Create mock resource
        resource = MagicMock()
        resource.attributes = {"service.name": "test-service"}

        # Create mock resource metrics
        resource_metrics = MagicMock()
        resource_metrics.resource = resource
        resource_metrics.scope_metrics = [scope_metrics]

        # Create mock metrics data
        metrics_data = MagicMock()
        metrics_data.resource_metrics = [resource_metrics]

        return metrics_data

    def test_histogram_export_creates_four_metrics(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            histogram_as_values=False,  # Use derived metrics mode
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_histogram_data(
            metric_name="request_latency",
            metric_unit="ms",
            count=50,
            sum_value=2500.0,
            min_value=5.0,
            max_value=150.0,
            attributes={"endpoint": "/api"},
        )

        from opentelemetry.sdk.metrics.export import MetricExportResult

        result = exporter.export(metrics_data)

        assert result == MetricExportResult.SUCCESS

        output.seek(0)
        line = output.readline()
        emf = json.loads(line)

        # Check that all four histogram metrics are present
        assert emf["request_latency_count"] == 50
        assert emf["request_latency_sum"] == 2500.0
        assert emf["request_latency_min"] == 5.0
        assert emf["request_latency_max"] == 150.0

        # Check metrics definition
        cw_metrics = emf["_aws"]["CloudWatchMetrics"][0]
        metric_names = [m["Name"] for m in cw_metrics["Metrics"]]
        assert "request_latency_count" in metric_names
        assert "request_latency_sum" in metric_names
        assert "request_latency_min" in metric_names
        assert "request_latency_max" in metric_names

    def test_histogram_count_uses_count_unit(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            histogram_as_values=False,
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_histogram_data()

        exporter.export(metrics_data)

        output.seek(0)
        emf = json.loads(output.readline())

        cw_metrics = emf["_aws"]["CloudWatchMetrics"][0]
        metrics_by_name = {m["Name"]: m for m in cw_metrics["Metrics"]}

        # Count should always use "Count" unit
        assert metrics_by_name["latency_count"]["Unit"] == "Count"
        # Sum/min/max should use the metric's unit
        assert metrics_by_name["latency_sum"]["Unit"] == "Milliseconds"
        assert metrics_by_name["latency_min"]["Unit"] == "Milliseconds"
        assert metrics_by_name["latency_max"]["Unit"] == "Milliseconds"

    def test_histogram_with_zero_count_skips_count_metric(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            histogram_as_values=False,
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_histogram_data(count=0)

        exporter.export(metrics_data)

        output.seek(0)
        emf = json.loads(output.readline())

        # Count metric should not be present when count is 0
        assert "latency_count" not in emf

    def test_histogram_with_none_values(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            histogram_as_values=False,
            auto_detect_aws=False,
        )

        # Create histogram with None min/max (can happen with no observations)
        metrics_data = self.create_mock_histogram_data(
            count=0,
            sum_value=None,
            min_value=None,
            max_value=None,
        )

        exporter.export(metrics_data)

        output.seek(0)
        content = output.read()

        # Should still produce valid output (possibly empty if all values are None/0)
        if content.strip():
            emf = json.loads(content.strip())
            # Should not contain None values as metric values
            assert "latency_count" not in emf or emf.get("latency_count") != 0

    def test_histogram_derived_skips_non_finite_values(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            histogram_as_values=False,
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_histogram_data(
            count=2,
            sum_value=math.inf,
            min_value=math.nan,
            max_value=10.0,
        )

        from opentelemetry.sdk.metrics.export import MetricExportResult

        result = exporter.export(metrics_data)
        assert result == MetricExportResult.SUCCESS

        output.seek(0)
        emf = json.loads(output.readline())

        assert "latency_count" in emf
        assert "latency_sum" not in emf
        assert "latency_min" not in emf
        assert emf["latency_max"] == 10.0


class TestHistogramExportValues:
    """Test histogram export with Values arrays for percentile support."""

    def create_mock_histogram_data_with_buckets(
        self,
        metric_name: str = "latency",
        metric_unit: str = "ms",
        count: int = 100,
        bucket_counts: list = None,
        explicit_bounds: list = None,
        min_value: float = None,
        max_value: float = None,
    ) -> MagicMock:
        """Create histogram with bucket data."""
        if bucket_counts is None:
            bucket_counts = [10, 30, 40, 15, 5]
        if explicit_bounds is None:
            explicit_bounds = [10, 50, 100, 200]

        data_point = MagicMock()
        data_point.count = count
        data_point.sum = 5000.0
        data_point.min = min_value or 5.0
        data_point.max = max_value or 300.0
        data_point.attributes = {}
        data_point.bucket_counts = bucket_counts
        data_point.explicit_bounds = explicit_bounds

        histogram_data = MagicMock()
        histogram_data.data_points = [data_point]

        metric = MagicMock()
        metric.name = metric_name
        metric.unit = metric_unit
        metric.data = histogram_data

        from opentelemetry.sdk.metrics.export import Histogram

        metric.data.__class__ = Histogram

        scope_metrics = MagicMock()
        scope_metrics.metrics = [metric]

        resource = MagicMock()
        resource.attributes = {}

        resource_metrics = MagicMock()
        resource_metrics.resource = resource
        resource_metrics.scope_metrics = [scope_metrics]

        metrics_data = MagicMock()
        metrics_data.resource_metrics = [resource_metrics]

        return metrics_data

    def test_histogram_values_mode_emits_values(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            histogram_as_values=True,  # Default, but explicit
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_histogram_data_with_buckets()

        from opentelemetry.sdk.metrics.export import MetricExportResult

        result = exporter.export(metrics_data)
        assert result == MetricExportResult.SUCCESS

        output.seek(0)
        line = output.readline()
        emf = json.loads(line)

        # Should have the metric name as a key with values
        assert "latency" in emf
        # Values should be present (either single value or array)
        assert emf["latency"] is not None

    def test_histogram_to_values_counts_conversion(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            auto_detect_aws=False,
        )

        # Create a data point with buckets
        data_point = MagicMock()
        data_point.count = 100
        data_point.sum = 5000.0
        data_point.min = 5.0
        data_point.max = 300.0
        data_point.bucket_counts = [10, 30, 40, 15, 5]  # 5 buckets
        data_point.explicit_bounds = [10, 50, 100, 200]  # 4 bounds

        values, counts = exporter._histogram_to_values_counts(data_point)

        # Should have values for non-zero buckets
        assert len(values) > 0
        assert len(values) == len(counts)
        # All counts should be positive
        assert all(c > 0 for c in counts)

    def test_histogram_no_bucket_fallback_requires_min_and_max(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            auto_detect_aws=False,
        )

        data_point = MagicMock()
        data_point.count = 2
        data_point.min = 5.0
        data_point.max = None
        data_point.bucket_counts = None
        data_point.explicit_bounds = None

        assert exporter._histogram_to_values_counts(data_point) == ([], [])

    def test_histogram_values_mode_expands_counts(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_histogram_data_with_buckets(
            bucket_counts=[2, 3],
            explicit_bounds=[10],
        )

        exporter.export(metrics_data)

        output.seek(0)
        emf = json.loads(output.readline())

        assert emf["latency"] == [5.0, 5.0, 15.0, 15.0, 15.0]

    def test_histogram_values_mode_caps_expanded_values(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_histogram_data_with_buckets(
            bucket_counts=[1000, 1000, 1000],
            explicit_bounds=[10, 20],
        )

        exporter.export(metrics_data)

        output.seek(0)
        emf = json.loads(output.readline())

        assert len(emf["latency"]) == 100
        assert set(emf["latency"]) == {5.0, 15.0, 30.0}

    def test_histogram_values_mode_samples_across_many_buckets(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )

        metrics_data = self.create_mock_histogram_data_with_buckets(
            bucket_counts=[1] * 200,
            explicit_bounds=list(range(1, 200)),
        )

        exporter.export(metrics_data)

        output.seek(0)
        emf = json.loads(output.readline())

        assert len(emf["latency"]) == 100
        assert min(emf["latency"]) < 5
        assert max(emf["latency"]) > 190


class TestOpenTelemetrySDKIntegration:
    """Test export through the public OpenTelemetry SDK path."""

    def test_counter_exports_from_meter_provider(self):
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource

        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )
        reader = PeriodicExportingMetricReader(
            exporter,
            export_interval_millis=600000,
        )
        provider = MeterProvider(
            metric_readers=[reader],
            resource=Resource.create({"service.name": "sdk-service"}),
        )

        meter = provider.get_meter("integration-test")
        counter = meter.create_counter("requests", unit="1")
        counter.add(3, {"endpoint": "/sdk"})

        assert provider.force_flush() is True
        provider.shutdown()

        output.seek(0)
        emf = json.loads(output.readline())

        assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "TestApp"
        assert emf["requests"] == 3
        assert emf["service_name"] == "sdk-service"
        assert emf["endpoint"] == "/sdk"

    def test_histogram_exports_values_from_meter_provider(self):
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        output = io.StringIO()
        exporter = CloudWatchEMFExporter(
            namespace="TestApp",
            output=output,
            timestamp_fn=lambda: 1700000000000,
            auto_detect_aws=False,
        )
        reader = PeriodicExportingMetricReader(
            exporter,
            export_interval_millis=600000,
        )
        provider = MeterProvider(metric_readers=[reader])

        meter = provider.get_meter("integration-test")
        histogram = meter.create_histogram("latency", unit="ms")
        histogram.record(10, {"route": "/sdk"})
        histogram.record(20, {"route": "/sdk"})

        assert provider.force_flush() is True
        provider.shutdown()

        output.seek(0)
        emf = json.loads(output.readline())

        assert emf["_aws"]["CloudWatchMetrics"][0]["Namespace"] == "TestApp"
        assert "latency" in emf
        assert emf["route"] == "/sdk"


class TestForceFlushAndShutdown:
    """Test force_flush and shutdown methods."""

    def test_force_flush_returns_true(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(namespace="Test", output=output, auto_detect_aws=False)
        assert exporter.force_flush() is True

    def test_shutdown_sets_flag(self):
        output = io.StringIO()
        exporter = CloudWatchEMFExporter(namespace="Test", output=output, auto_detect_aws=False)
        assert exporter._shutdown is False
        exporter.shutdown()
        assert exporter._shutdown is True


class TestThreadSafety:
    """Test thread safety of the exporter."""

    def test_shutdown_is_thread_safe(self):
        import threading

        output = io.StringIO()
        exporter = CloudWatchEMFExporter(namespace="Test", output=output, auto_detect_aws=False)

        # Verify lock exists
        assert hasattr(exporter, "_lock")
        assert isinstance(exporter._lock, type(threading.Lock()))

    def test_concurrent_export_and_shutdown(self):
        import threading

        output = io.StringIO()
        exporter = CloudWatchEMFExporter(namespace="Test", output=output, auto_detect_aws=False)

        results = []

        def do_shutdown():
            exporter.shutdown()

        def do_export():
            # Create minimal mock metrics data
            metrics_data = MagicMock()
            metrics_data.resource_metrics = []
            result = exporter.export(metrics_data)
            results.append(result)

        threads = [
            threading.Thread(target=do_shutdown),
            threading.Thread(target=do_export),
            threading.Thread(target=do_export),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should complete without errors
        assert exporter._shutdown is True
