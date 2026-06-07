# Community Gap

This package addresses a narrow but recurring OpenTelemetry/AWS integration gap:
Python applications that want to emit CloudWatch Embedded Metric Format (EMF)
directly through stdout or logs without running the AWS Distro for OpenTelemetry
Collector, CloudWatch Agent, or a sidecar.

## Current Upstream Shape

- OpenTelemetry documents the AWS CloudWatch EMF exporter as a Collector contrib
  exporter, not as a Python SDK exporter:
  <https://opentelemetry.io/docs/collector/components/exporter/>
- AWS CloudWatch documentation describes the OpenTelemetry EMF path as requiring
  an OpenTelemetry data source plus AWS Distro for OpenTelemetry Collector with
  CloudWatch EMF logs enabled:
  <https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_OpenTelemetry.html>
- ADOT documentation likewise routes CloudWatch metrics through the ADOT
  Collector:
  <https://aws-otel.github.io/docs/getting-started/cloudwatch-metrics>
- Collector-side EMF behavior has had long-running operational pain points, for
  example batching around EMF event limits:
  <https://github.com/open-telemetry/opentelemetry-collector-contrib/issues/26073>

## What This Package Does

This package provides an unofficial Python `MetricExporter` that converts
OpenTelemetry metrics to CloudWatch EMF JSON and writes one JSON document per
line to stdout or another configured stream.

It is intended for deployments where a collector or sidecar is too much
operational overhead, especially:

- AWS Lambda functions
- ECS/Fargate services using `awslogs`
- EC2 processes writing logs collected by CloudWatch Agent
- Small Python services that already use OpenTelemetry SDK metrics

## What This Package Does Not Do

- It is not an official AWS, Amazon CloudWatch, ADOT, or OpenTelemetry project.
- It is not a replacement for the ADOT Collector when collector pipelines,
  processors, receivers, or multi-destination routing are needed.
- It does not call CloudWatch `PutMetricData`; it relies on CloudWatch Logs EMF
  ingestion.
