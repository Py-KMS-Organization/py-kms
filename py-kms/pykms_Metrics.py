#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Prometheus metrics module for py-kms server.

This module defines all Prometheus metrics for monitoring KMS server activity,
including activation requests, client statistics, and database metrics.
"""

import os
import logging
import time
import shelve
from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, generate_latest, CONTENT_TYPE_LATEST

loggersrv = logging.getLogger('logsrv')

# Check if metrics are enabled (default: enabled for python3 image with WebUI)
METRICS_ENABLED = os.environ.get('METRICS', '1') == '1'

# SKU detail level: NONE (default), CATEGORY, or DETAILED
# NONE - no SKU label (default, lowest cardinality)
# CATEGORY - SKU category (e.g., 'windows-10', 'office-2019', 'office-2021')
# DETAILED - full SKU name (e.g., 'Windows 10 Professional', 'Office 2019 ProPlus')
METRICS_SKU_DETAIL = os.environ.get('METRICS_SKU_DETAIL', 'NONE').upper()
if METRICS_SKU_DETAIL not in ['NONE', 'CATEGORY', 'DETAILED']:
    loggersrv.warning(f"Invalid METRICS_SKU_DETAIL value '{METRICS_SKU_DETAIL}'. Using 'NONE'.")
    METRICS_SKU_DETAIL = 'NONE'

# Duration labels level: BASIC (default), EXTENDED, or DETAILED
# BASIC - product label only (default, ~51 time series: 3 products × 17 buckets)
# EXTENDED - product + kms_version labels (~204 time series: 3 × 4 × 17)
# DETAILED - product + kms_version + sku labels (depends on METRICS_SKU_DETAIL, high cardinality)
METRICS_DURATION_LABELS = os.environ.get('METRICS_DURATION_LABELS', 'BASIC').upper()
if METRICS_DURATION_LABELS not in ['BASIC', 'EXTENDED', 'DETAILED']:
    loggersrv.warning(f"Invalid METRICS_DURATION_LABELS value '{METRICS_DURATION_LABELS}'. Using 'BASIC'.")
    METRICS_DURATION_LABELS = 'BASIC'

# Validate: DETAILED duration labels require SKU detail to be enabled
if METRICS_DURATION_LABELS == 'DETAILED' and METRICS_SKU_DETAIL == 'NONE':
    loggersrv.warning("METRICS_DURATION_LABELS=DETAILED requires METRICS_SKU_DETAIL to be enabled. Falling back to EXTENDED.")
    METRICS_DURATION_LABELS = 'EXTENDED'

# For multiprocess mode (Gunicorn with multiple workers)
# In multiprocess mode, metrics are registered to the default REGISTRY and written to files
# When collecting, we use MultiProcessCollector to aggregate from those files
if METRICS_ENABLED:
    try:
        from prometheus_client import REGISTRY
        
        # Check if we're in multiprocess mode (Gunicorn sets this)
        prometheus_multiproc_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR', os.environ.get('prometheus_multiproc_dir'))
        
        if prometheus_multiproc_dir:
            # Multiprocess mode (when running under Gunicorn)
            # In multiprocess mode, always use the default REGISTRY
            # The prometheus_client library will automatically handle writing to files
            loggersrv.info(f"Prometheus metrics: multiprocess mode enabled (dir: {prometheus_multiproc_dir})")
            registry = REGISTRY
        else:
            # Single process mode
            loggersrv.debug("Prometheus metrics: single process mode")
            registry = REGISTRY
    except ImportError:
        loggersrv.warning("prometheus_client module not available. Metrics will be disabled.")
        METRICS_ENABLED = False
        registry = None
else:
    loggersrv.info("Prometheus metrics disabled via METRICS environment variable.")
    registry = None

# ==============================================================================
# Time-windowed activation tracking (for low-traffic environments)
# ==============================================================================

# Shared storage for activation events using shelve (cross-process safe)
# Use PROMETHEUS_MULTIPROC_DIR if available, otherwise /tmp
_events_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR', os.environ.get('prometheus_multiproc_dir', '/tmp'))
_EVENTS_DB_PATH = os.path.join(_events_dir, 'pykms_activation_events')

# Maximum time window we track (5 minutes)
_MAX_WINDOW_SECONDS = 300

loggersrv.info(f"Using activation events storage at: {_EVENTS_DB_PATH}")

# ==============================================================================
# Service Information Metrics
# ==============================================================================

if METRICS_ENABLED:
    # For multiprocess mode, Gauge metrics need multiprocess_mode specified to avoid pid in labels
    # 'livesum' - sum across all live workers (good for counters-as-gauges)
    # 'liveall' - all values from all workers (creates separate series per worker)
    # 'max' - maximum value across all workers (good for binary 0/1 values)
    # 'min' - minimum value (good for timestamps)
    pykms_up = Gauge('pykms_up', 'Service availability (1 = up, 0 = down)', ['version'], 
                     registry=registry, multiprocess_mode='max')
    pykms_start_time_seconds = Gauge('pykms_start_time_seconds', 'Unix timestamp when the service started', 
                                      registry=registry, multiprocess_mode='min')
    pykms_info = Gauge('pykms_info', 'Service information (always 1)', ['version', 'python_version'], 
                       registry=registry, multiprocess_mode='max')

# ==============================================================================
# Request Metrics (from KMS Server)
# ==============================================================================

if METRICS_ENABLED:
    # Define labels based on SKU detail level for activation counter
    if METRICS_SKU_DETAIL == 'NONE':
        activation_labels = ['status', 'product', 'kms_version']
    else:
        activation_labels = ['status', 'product', 'kms_version', 'sku']
    
    # Define labels for duration histogram based on METRICS_DURATION_LABELS
    if METRICS_DURATION_LABELS == 'BASIC':
        duration_labels = ['product']
    elif METRICS_DURATION_LABELS == 'EXTENDED':
        duration_labels = ['product', 'kms_version']
    elif METRICS_DURATION_LABELS == 'DETAILED':
        duration_labels = ['product', 'kms_version', 'sku']
    else:
        duration_labels = ['product']  # Fallback to BASIC
    
    pykms_activation_requests_total = Counter(
        'pykms_activation_requests_total', 'Total number of KMS activation requests',
        activation_labels, registry=registry
    )
    
    loggersrv.info(f"Creating duration histogram with labels: {duration_labels}")
    pykms_activation_request_duration_seconds = Histogram(
        'pykms_activation_request_duration_seconds', 'Time spent processing activation requests',
        labelnames=duration_labels,
        buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0),
        registry=registry
    )
    pykms_active_connections = Gauge('pykms_active_connections', 'Current number of active TCP connections to KMS server', 
                                      registry=registry, multiprocess_mode='livesum')
    
    # Time-windowed activation metrics (for low-traffic environments)
    # These show activation counts over recent time windows, useful when connections are very short-lived
    # Using multiprocess_mode='max' because all workers read the same shelve data
    pykms_activations_last_30s = Gauge(
        'pykms_activations_last_30s', 'Number of activation requests in the last 30 seconds',
        ['status', 'product'], registry=registry, multiprocess_mode='max'
    )
    pykms_activations_last_60s = Gauge(
        'pykms_activations_last_60s', 'Number of activation requests in the last 60 seconds',
        ['status', 'product'], registry=registry, multiprocess_mode='max'
    )
    pykms_activations_last_300s = Gauge(
        'pykms_activations_last_300s', 'Number of activation requests in the last 300 seconds (5 minutes)',
        ['status', 'product'], registry=registry, multiprocess_mode='max'
    )

# ==============================================================================
# Client Metrics (from SQLite database)
# ==============================================================================

if METRICS_ENABLED:
    # Database metrics read the same data from all workers, use 'max' to avoid duplication
    pykms_clients_total = Gauge('pykms_clients_total', 'Total number of unique clients in database', ['application'], 
                                 registry=registry, multiprocess_mode='max')
    pykms_database_last_activation_by_application = Gauge(
        'pykms_database_last_activation_by_application', 'Unix timestamp of most recent activation by application type',
        ['application'], registry=registry, multiprocess_mode='max'
    )

# ==============================================================================
# Database Metrics
# ==============================================================================

if METRICS_ENABLED:
    # Database metrics: all workers read the same DB, use 'max' to avoid duplication
    pykms_database_size_bytes = Gauge('pykms_database_size_bytes', 'Size of SQLite database file in bytes', 
                                       registry=registry, multiprocess_mode='max')
    pykms_database_last_activation_timestamp = Gauge(
        'pykms_database_last_activation_timestamp', 'Unix timestamp of most recent activation in database', 
        registry=registry, multiprocess_mode='max'
    )
    pykms_database_total_requests = Gauge(
        'pykms_database_total_requests', 'Sum of all request counts from all clients in database', 
        registry=registry, multiprocess_mode='max'
    )


# ==============================================================================
# Helper Functions
# ==============================================================================

def get_product_type(app_name):
    """Determine product type from application name."""
    if not app_name:
        return "unknown"
    app_name_lower = str(app_name).lower()
    if "windows" in app_name_lower:
        return "windows"
    elif "office" in app_name_lower:
        return "office"
    else:
        return "unknown"

def get_kms_version(version_major):
    """Get KMS protocol version string from version major number."""
    if version_major in [4, 5, 6]:
        return f"v{version_major}"
    else:
        return "unknown"

def get_sku_category(sku_name):
    """
    Extract SKU category from full SKU name.
    
    Examples:
    - 'Windows 10 Professional' -> 'windows-10'
    - 'Office 2019 ProPlus' -> 'office-2019'
    - 'Windows Server 2016 Datacenter' -> 'windows-server-2016'
    """
    if not sku_name:
        return "unknown"
    
    sku_lower = str(sku_name).lower()
    
    # Windows patterns
    if 'windows' in sku_lower:
        if 'server' in sku_lower:
            # Extract Windows Server version
            for year in ['2025', '2022', '2019', '2016', '2012']:
                if year in sku_lower:
                    return f"windows-server-{year}"
            return "windows-server"
        else:
            # Extract Windows client version
            if 'windows 11' in sku_lower or 'windows11' in sku_lower:
                return "windows-11"
            elif 'windows 10' in sku_lower or 'windows10' in sku_lower:
                return "windows-10"
            elif 'windows 8' in sku_lower or 'windows8' in sku_lower:
                return "windows-8"
            elif 'windows 7' in sku_lower or 'windows7' in sku_lower:
                return "windows-7"
            return "windows"
    
    # Office patterns
    elif 'office' in sku_lower:
        for year in ['2024', '2021', '2019', '2016', '2013']:
            if year in sku_lower:
                return f"office-{year}"
        return "office"
    
    return "unknown"

def get_sku_label(sku_name, app_name):
    """
    Get SKU label based on METRICS_SKU_DETAIL level.
    
    Args:
        sku_name: SKU name (e.g., 'Windows 10 Professional')
        app_name: Application name (for fallback)
    
    Returns:
        SKU label string based on detail level, or None if SKU detail is disabled
    """
    if METRICS_SKU_DETAIL == 'NONE':
        return None
    elif METRICS_SKU_DETAIL == 'CATEGORY':
        return get_sku_category(sku_name if sku_name else app_name)
    elif METRICS_SKU_DETAIL == 'DETAILED':
        # Return full SKU name, sanitized for Prometheus labels
        if sku_name and str(sku_name).strip():
            # Replace problematic characters for Prometheus labels
            sanitized = str(sku_name).replace('"', '').replace("'", "").replace('\\', '')
            return sanitized if sanitized != 'None' else 'unknown'
        return 'unknown'
    return None

def _update_windowed_metrics():
    """
    Update time-windowed activation metrics by reading from shelve storage.
    Cleans up events older than _MAX_WINDOW_SECONDS.
    This function is called when metrics are collected (/metrics endpoint).
    """
    if not METRICS_ENABLED:
        return
    
    current_time = time.time()
    
    try:
        # Open shelve database
        with shelve.open(_EVENTS_DB_PATH) as db:
            # Get events list, default to empty if not exists
            events = db.get('events', [])
            
            loggersrv.debug(f"Updating windowed metrics: shelve has {len(events)} events")
            
            # Remove events older than the maximum window
            events = [(t, s, p) for t, s, p in events if t > current_time - _MAX_WINDOW_SECONDS]
            
            loggersrv.debug(f"After cleanup: {len(events)} events remain")
            
            # Save cleaned events back
            db['events'] = events
            
            # Count events for each time window
            counts_30s = {}
            counts_60s = {}
            counts_300s = {}
            
            cutoff_30s = current_time - 30
            cutoff_60s = current_time - 60
            cutoff_300s = current_time - 300
            
            for timestamp, status, product in events:
                key = (status, product)
                
                if timestamp >= cutoff_30s:
                    counts_30s[key] = counts_30s.get(key, 0) + 1
                if timestamp >= cutoff_60s:
                    counts_60s[key] = counts_60s.get(key, 0) + 1
                if timestamp >= cutoff_300s:
                    counts_300s[key] = counts_300s.get(key, 0) + 1
            
            loggersrv.info(f"Windowed counts - 30s: {counts_30s}, 60s: {counts_60s}, 300s: {counts_300s}")
            
            # Update metrics with absolute values
            # Using multiprocess_mode='max', all workers read same shelve, one value wins
            for status in ['success', 'failure']:
                for product in ['windows', 'office', 'unknown']:
                    key = (status, product)
                    
                    count_30s = counts_30s.get(key, 0)
                    count_60s = counts_60s.get(key, 0)
                    count_300s = counts_300s.get(key, 0)
                    
                    if count_30s > 0 or count_60s > 0 or count_300s > 0:
                        loggersrv.info(f"Setting metrics for {status}/{product}: 30s={count_30s}, 60s={count_60s}, 300s={count_300s}")
                    
                    pykms_activations_last_30s.labels(status=status, product=product).set(count_30s)
                    pykms_activations_last_60s.labels(status=status, product=product).set(count_60s)
                    pykms_activations_last_300s.labels(status=status, product=product).set(count_300s)
                    
    except Exception as e:
        loggersrv.error(f"Failed to update windowed metrics from shelve: {e}", exc_info=True)

def record_activation_request(status, product, kms_version, duration=None, sku=None):
    """
    Record an activation request with metrics.
    
    Args:
        status: 'success' or 'failure'
        product: Product type ('windows', 'office', 'unknown')
        kms_version: KMS version ('v4', 'v5', 'v6', 'unknown')
        duration: Request duration in seconds (optional)
        sku: SKU label (optional, used only if METRICS_SKU_DETAIL/METRICS_DURATION_LABELS require it)
    """
    if not METRICS_ENABLED:
        loggersrv.debug("Metrics disabled, skipping record_activation_request")
        return
    
    loggersrv.info(f"Recording activation metric: status={status}, product={product}, kms_version={kms_version}, sku={sku}, duration={duration}")
    
    try:
        # Record activation counter (uses METRICS_SKU_DETAIL)
        if METRICS_SKU_DETAIL == 'NONE':
            loggersrv.debug(f"Recording activation counter without SKU: status={status}, product={product}, kms_version={kms_version}")
            pykms_activation_requests_total.labels(status=status, product=product, kms_version=kms_version).inc()
        else:
            sku_label = sku if sku else 'unknown'
            loggersrv.debug(f"Recording activation counter with SKU: status={status}, product={product}, kms_version={kms_version}, sku={sku_label}")
            pykms_activation_requests_total.labels(status=status, product=product, kms_version=kms_version, sku=sku_label).inc()
        
        # Record duration histogram (uses METRICS_DURATION_LABELS)
        if duration is not None:
            if METRICS_DURATION_LABELS == 'BASIC':
                loggersrv.debug(f"Recording duration with BASIC labels: product={product}, duration={duration}s")
                pykms_activation_request_duration_seconds.labels(product=product).observe(duration)
            elif METRICS_DURATION_LABELS == 'EXTENDED':
                loggersrv.debug(f"Recording duration with EXTENDED labels: product={product}, kms_version={kms_version}, duration={duration}s")
                pykms_activation_request_duration_seconds.labels(product=product, kms_version=kms_version).observe(duration)
            elif METRICS_DURATION_LABELS == 'DETAILED':
                sku_label = sku if sku else 'unknown'
                loggersrv.debug(f"Recording duration with DETAILED labels: product={product}, kms_version={kms_version}, sku={sku_label}, duration={duration}s")
                pykms_activation_request_duration_seconds.labels(product=product, kms_version=kms_version, sku=sku_label).observe(duration)
        
        # Add event to shared shelve storage (for time-based metrics)
        try:
            with shelve.open(_EVENTS_DB_PATH) as db:
                events = db.get('events', [])
                events.append((time.time(), status, product))
                db['events'] = events
                loggersrv.debug(f"Added activation event to shelve, total events: {len(events)}")
        except Exception as e:
            loggersrv.error(f"Failed to save activation event to shelve: {e}")
        
        loggersrv.info(f"Successfully recorded activation metric")
    except Exception as e:
        loggersrv.error(f"Failed to record activation request metrics: {e}", exc_info=True)

def increment_active_connections():
    """Increment active connections counter."""
    if not METRICS_ENABLED:
        return
    try:
        pykms_active_connections.inc()
    except Exception as e:
        loggersrv.warning(f"Failed to increment active connections: {e}")

def decrement_active_connections():
    """Decrement active connections counter."""
    if not METRICS_ENABLED:
        return
    try:
        pykms_active_connections.dec()
    except Exception as e:
        loggersrv.warning(f"Failed to decrement active connections: {e}")

def update_database_metrics(db_path, clients):
    """Update database-related metrics."""
    if not METRICS_ENABLED:
        return
    try:
        if os.path.exists(db_path):
            db_size = os.path.getsize(db_path)
            pykms_database_size_bytes.set(db_size)
        
        if clients:
            windows_count = 0
            office_count = 0
            total_requests = 0
            last_activation = 0
            last_activation_windows = 0
            last_activation_office = 0
            
            for client in clients:
                app_type = get_product_type(client.get('applicationId', ''))
                if app_type == 'windows':
                    windows_count += 1
                elif app_type == 'office':
                    office_count += 1
                
                request_count = client.get('requestCount', 0)
                if request_count:
                    total_requests += request_count
                
                last_request_time = client.get('lastRequestTime')
                if last_request_time:
                    if isinstance(last_request_time, str):
                        from datetime import datetime
                        try:
                            dt = datetime.fromisoformat(last_request_time)
                            last_request_timestamp = int(dt.timestamp())
                        except:
                            last_request_timestamp = 0
                    else:
                        last_request_timestamp = int(last_request_time)
                    
                    if last_request_timestamp > last_activation:
                        last_activation = last_request_timestamp
                    
                    # Track last activation by application type (no client_id to avoid high cardinality)
                    if app_type == 'windows' and last_request_timestamp > last_activation_windows:
                        last_activation_windows = last_request_timestamp
                    elif app_type == 'office' and last_request_timestamp > last_activation_office:
                        last_activation_office = last_request_timestamp
            
            pykms_clients_total.labels(application='windows').set(windows_count)
            pykms_clients_total.labels(application='office').set(office_count)
            pykms_database_total_requests.set(total_requests)
            
            if last_activation > 0:
                pykms_database_last_activation_timestamp.set(last_activation)
            
            # Set last activation by application type
            if last_activation_windows > 0:
                pykms_database_last_activation_by_application.labels(application='windows').set(last_activation_windows)
            if last_activation_office > 0:
                pykms_database_last_activation_by_application.labels(application='office').set(last_activation_office)
    except Exception as e:
        loggersrv.warning(f"Failed to update database metrics: {e}")

def initialize_metrics(version_string, python_version):
    """Initialize service metrics."""
    if not METRICS_ENABLED:
        return
    try:
        pykms_up.labels(version=version_string).set(1)
        pykms_start_time_seconds.set(time.time())
        pykms_info.labels(version=version_string, python_version=python_version).set(1)
        loggersrv.info("Prometheus metrics initialized successfully")
    except Exception as e:
        loggersrv.warning(f"Failed to initialize metrics: {e}")

def get_metrics_output():
    """Generate Prometheus metrics output."""
    if not METRICS_ENABLED or registry is None:
        return ("text/plain", b"Metrics disabled")
    try:
        # Update windowed metrics before generating output
        _update_windowed_metrics()
        
        prometheus_multiproc_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR', os.environ.get('prometheus_multiproc_dir'))
        if prometheus_multiproc_dir:
            from prometheus_client import multiprocess, CollectorRegistry
            local_registry = CollectorRegistry()
            multiprocess.MultiProcessCollector(local_registry)
            metrics = generate_latest(local_registry)
        else:
            metrics = generate_latest(registry)
        return (CONTENT_TYPE_LATEST, metrics)
    except Exception as e:
        loggersrv.error(f"Failed to generate metrics: {e}")
        return ("text/plain", f"Error generating metrics: {e}".encode('utf-8'))

# Initialize all windowed metrics to 0
if METRICS_ENABLED:
    pykms_active_connections.set(0)
    
    # Initialize windowed metrics with all label combinations set to 0
    for status in ['success', 'failure']:
        for product in ['windows', 'office', 'unknown']:
            pykms_activations_last_30s.labels(status=status, product=product).set(0)
            pykms_activations_last_60s.labels(status=status, product=product).set(0)
            pykms_activations_last_300s.labels(status=status, product=product).set(0)
    
    loggersrv.info("Initialized windowed activation metrics with zero values")

