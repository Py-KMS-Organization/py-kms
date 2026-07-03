#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Gunicorn configuration file for py-kms WebUI with Prometheus multiprocess support.
"""

import os
import logging

# Gunicorn logging
accesslog = '-'
errorlog = '-'
loglevel = os.environ.get('LOGLEVEL', 'info').lower()
if loglevel == 'mininfo':
    loglevel = 'info'

# Server socket
bind = '0.0.0.0:8080'

# Worker processes
workers = 2
worker_class = 'sync'
worker_connections = 1000
timeout = 30
keepalive = 2

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None

# Worker lifecycle hooks for Prometheus multiprocess mode
def child_exit(server, worker):
    """
    Called just after a worker has been exited, in the master process.
    This is where we mark dead workers for prometheus_client.
    """
    try:
        from prometheus_client import multiprocess
        prometheus_multiproc_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR', 
                                                   os.environ.get('prometheus_multiproc_dir'))
        if prometheus_multiproc_dir:
            multiprocess.mark_process_dead(worker.pid)
            logging.info(f"Marked Prometheus metrics for worker {worker.pid} as dead")
    except Exception as e:
        logging.warning(f"Failed to mark dead worker for Prometheus: {e}")


def when_ready(server):
    """
    Called just after the server is started.
    Clean up any stale metrics files from previous runs.
    """
    try:
        from prometheus_client import multiprocess
        prometheus_multiproc_dir = os.environ.get('PROMETHEUS_MULTIPROC_DIR',
                                                   os.environ.get('prometheus_multiproc_dir'))
        if prometheus_multiproc_dir and os.path.exists(prometheus_multiproc_dir):
            # Clean up any leftover .db files from previous runs
            for filename in os.listdir(prometheus_multiproc_dir):
                if filename.endswith('.db'):
                    filepath = os.path.join(prometheus_multiproc_dir, filename)
                    try:
                        os.remove(filepath)
                        logging.info(f"Cleaned up old Prometheus metrics file: {filename}")
                    except Exception as e:
                        logging.warning(f"Failed to remove {filename}: {e}")
    except Exception as e:
        logging.warning(f"Failed to clean up Prometheus multiprocess directory: {e}")
