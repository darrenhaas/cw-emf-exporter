# Changelog

## 0.2.5

- Skip non-finite metric values so EMF output remains valid JSON for
  CloudWatch ingestion.
- Drop dimensions that would collide with emitted metric names.
- Preserve point attribute priority when `max_dimensions` caps dimension count.
- Enforce import ordering in CI and release checks.
- Complete the API unit mapping table.

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
