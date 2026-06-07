# Changelog

## 0.2.4

Initial public release.

- Added collectorless OpenTelemetry metrics export to CloudWatch EMF JSON.
- Added counter, gauge, histogram, and exponential histogram support.
- Sample large histograms across the full distribution while respecting EMF's
  100-value numeric array limit.
- Return `MetricExportResult.FAILURE` when output writes fail.
- Harden ECS metadata detection against malformed responses and unavailable
  metadata endpoints.
- Added Python 3.9 through 3.13 support metadata.
- Added CI for tests, type checking, linting, package build, and `twine check`.
