# Prometheus Metrics Documentation

## Overview

py-kms server (python3 Docker image only) supports exporting metrics in Prometheus format for monitoring and observability. This feature is designed for testing, learning, and lab environments to better understand KMS activation protocol behavior.

## Availability

**Metrics are available ONLY in the `python3` Docker image**, not in the `minimal` image.

- **python3 image**: Includes Flask, Gunicorn, SQLite, and metrics support
- **minimal image**: Lightweight, no WebUI or metrics

## Configuration

### Enabling/Disabling Metrics

Metrics are **enabled by default** in the python3 image. To disable set METRICS environment variable to 0:

```bash
docker run -e METRICS=0 pykmsorg/py-kms:python3
```

### SKU Detail Level

Control the level of SKU (Stock Keeping Unit) detail in activation counter metrics using the `METRICS_SKU_DETAIL` environment variable:

- **`NONE`** (default): No SKU label, lowest cardinality
- **`CATEGORY`**: SKU category (e.g., `windows-10`, `office-2019`, `windows-server-2022`)
- **`DETAILED`**: Full SKU name (e.g., `Windows 10 Professional`, `Office 2019 ProPlus`)

```bash
# Default: no SKU label
docker run pykmsorg/py-kms:python3

# Category level (low cardinality)
docker run -e METRICS_SKU_DETAIL=CATEGORY pykmsorg/py-kms:python3

# Detailed level (may increase cardinality)
docker run -e METRICS_SKU_DETAIL=DETAILED pykmsorg/py-kms:python3
```

### Duration Histogram Labels

Control labels on the duration histogram metric to manage cardinality using the `METRICS_DURATION_LABELS` environment variable:

- **`BASIC`** (default): Only `product` label (~51 time series: 3 products × 17 buckets)
- **`EXTENDED`**: Add `product` and `kms_version` labels (~204 time series: 3 × 4 × 17)
- **`DETAILED`**: Add `product`, `kms_version`, and `sku` labels (requires `METRICS_SKU_DETAIL` to be enabled, high cardinality)

```bash
# Default: BASIC (product label only)
docker run pykmsorg/py-kms:python3

# EXTENDED: if you need to track performance by product and KMS version
docker run -e METRICS_DURATION_LABELS=EXTENDED pykmsorg/py-kms:python3

# DETAILED: for per-SKU performance analysis (requires METRICS_SKU_DETAIL)
docker run -e METRICS_SKU_DETAIL=CATEGORY -e METRICS_DURATION_LABELS=DETAILED pykmsorg/py-kms:python3
```

**Recommendation**: For most use cases, `BASIC` (default) is sufficient as it provides product-level breakdown with minimal cardinality impact. Use `EXTENDED` if you need to compare performance between KMS protocol versions, and `DETAILED` only for deep SKU-level analysis.

**Cardinality Impact**:

- `BASIC`: ~51 time series (3 products × 17 buckets/counters)
- `EXTENDED`: ~204 time series (3 products × 4 versions × 17)
- `DETAILED` with CATEGORY: ~3,000+ time series (depends on SKU count)

### Accessing Metrics

Metrics are exposed on the same port as the WebUI (default: 8080):

[http://localhost:8080/metrics](http://localhost:8080/metrics)

## Available Metrics

### Service Information Metrics

#### `pykms_up{version="..."}`

- **Type**: Gauge
- **Description**: Service availability (1 = up, 0 = down)
- **Labels**: `version` - py-kms version string

#### `pykms_start_time_seconds`

- **Type**: Gauge
- **Description**: Unix timestamp when the service started

#### `pykms_info{version="...", python_version="..."}`

- **Type**: Info
- **Description**: Service information including versions

### Request Metrics

#### `pykms_activation_requests_total{status, product, kms_version [, sku]}`

- **Type**: Counter
- **Description**: Total number of KMS activation requests
- **Labels**:
  - `status`: `success` or `failure`
  - `product`: `windows`, `office`, or `unknown`
  - `kms_version`: `v4`, `v5`, `v6`, or `unknown`
  - `sku` (optional): SKU information, included only if `METRICS_SKU_DETAIL` is not `NONE`
    - When `CATEGORY`: e.g., `windows-10`, `office-2019`, `windows-server-2022`
    - When `DETAILED`: e.g., `Windows 10 Professional`, `Office 2019 ProPlus`

#### `pykms_activation_request_duration_seconds{product [, kms_version [, sku]]}`

- **Type**: Histogram
- **Description**: Time spent processing activation requests
- **Labels** (configurable via `METRICS_DURATION_LABELS`):
  - `BASIC` (default): `product` only
  - `EXTENDED`: `product`, `kms_version`
  - `DETAILED`: `product`, `kms_version`, `sku` (requires `METRICS_SKU_DETAIL` enabled)
- **Buckets**: 0.001 to 10.0 seconds

#### `pykms_active_connections`

- **Type**: Gauge
- **Description**: Current number of active TCP connections to KMS server

#### `pykms_activations_last_30s{status, product}`

- **Type**: Gauge
- **Description**: Number of activation requests in the last 30 seconds
- **Labels**:
  - `status`: `success` or `failure`
  - `product`: `windows`, `office`, or `unknown`
- **Use Case**: Useful for low-traffic environments where `pykms_active_connections` is usually 0 due to short-lived connections

#### `pykms_activations_last_60s{status, product}`

- **Type**: Gauge
- **Description**: Number of activation requests in the last 60 seconds (1 minute)
- **Labels**:
  - `status`: `success` or `failure`
  - `product`: `windows`, `office`, or `unknown`
- **Use Case**: Shows recent activation activity even when Prometheus scrape interval might miss short connections

#### `pykms_activations_last_300s{status, product}`

- **Type**: Gauge
- **Description**: Number of activation requests in the last 300 seconds (5 minutes)
- **Labels**:
  - `status`: `success` or `failure`
  - `product`: `windows`, `office`, or `unknown`
- **Use Case**: Provides a longer window view of activation activity

### Client Metrics

#### `pykms_clients_total{application}`

- **Type**: Gauge
- **Description**: Total unique clients in database
- **Labels**: `application` - `windows` or `office`

#### `pykms_database_last_activation_by_application{application}`

- **Type**: Gauge
- **Description**: Unix timestamp of most recent activation by application type
- **Labels**: `application` - `windows` or `office`
- **Note**: Avoids high cardinality by not tracking individual clients

### Database Metrics

#### `pykms_database_size_bytes`

- **Type**: Gauge
- **Description**: Size of SQLite database file in bytes

#### `pykms_database_last_activation_timestamp`

- **Type**: Gauge
- **Description**: Unix timestamp of most recent activation

#### `pykms_database_total_requests`

- **Type**: Gauge
- **Description**: Sum of all request counts from all clients

## Example Queries

### Service Health

```promql
# Service uptime in hours
(time() - pykms_start_time_seconds) / 3600
```

### Activation Analysis

```promql
# Activation requests per minute
rate(pykms_activation_requests_total[5m]) * 60

# Failed vs successful ratio
rate(pykms_activation_requests_total{status="failure"}[5m]) / rate(pykms_activation_requests_total[5m])

# Breakdown by product type
sum by (product) (rate(pykms_activation_requests_total[5m]))

# Breakdown by SKU category (when METRICS_SKU_DETAIL=CATEGORY)
sum by (sku) (rate(pykms_activation_requests_total[5m]))

# Windows 10 and Windows 11 activations (with CATEGORY level)
sum by (sku) (rate(pykms_activation_requests_total{product="windows"}[5m]))

# Office versions breakdown (with CATEGORY level)
sum by (sku) (rate(pykms_activation_requests_total{product="office"}[5m]))
```

### Performance Monitoring

```promql
# Overall P95 latency (works with all METRICS_DURATION_LABELS levels)
histogram_quantile(0.95, rate(pykms_activation_request_duration_seconds_bucket[5m]))

# Average request duration (works with all METRICS_DURATION_LABELS levels)
rate(pykms_activation_request_duration_seconds_sum[5m]) / rate(pykms_activation_request_duration_seconds_count[5m])

# P95 latency by product (works with BASIC, EXTENDED, or DETAILED)
histogram_quantile(0.95, sum by (product, le) (rate(pykms_activation_request_duration_seconds_bucket[5m])))

# P95 latency by KMS version (requires METRICS_DURATION_LABELS=EXTENDED or DETAILED)
histogram_quantile(0.95, sum by (kms_version, le) (rate(pykms_activation_request_duration_seconds_bucket[5m])))

# P95 latency by SKU category (requires METRICS_DURATION_LABELS=DETAILED)
histogram_quantile(0.95, sum by (sku, le) (rate(pykms_activation_request_duration_seconds_bucket[5m])))
```

### Low-Traffic Environment Monitoring

```promql
# Total activations in the last 30 seconds (useful when connections are short-lived)
sum(pykms_activations_last_30s)

# Successful Windows activations in the last minute
pykms_activations_last_60s{status="success", product="windows"}

# Failed activations in the last 5 minutes
sum by (product) (pykms_activations_last_300s{status="failure"})

# Total activation activity in the last 5 minutes (all products)
sum(pykms_activations_last_300s)

# Success rate in the last minute (percentage)
100 * sum(pykms_activations_last_60s{status="success"}) / sum(pykms_activations_last_60s)

# Windows vs Office activations in the last 5 minutes
sum by (product) (pykms_activations_last_300s{status="success"})
```

## See Also

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [prometheus_client](https://github.com/prometheus/client_python)
