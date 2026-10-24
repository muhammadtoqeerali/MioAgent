"""Authenticated read-only resource telemetry for the machine running MioAgent API.

No arbitrary filesystem paths, shell, persistence, tool grants, or host mutations.
All usage claims identify their sampling source. Missing GPU tools show unavailable.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI

from mio.config import Settings
from mio.work_core import RUNTIME

LIMIT_BYTES = 128_000


def _cpu_snapshot() -> tuple[int, int] | None:
    try:
        with Path('/proc/stat').open('r', encoding='ascii') as fp:
            first = fp.readline(180)
        parts = first.split()
        if parts[0] != 'cpu' or len(parts) < 5:
            return None
        ticks = [int(x) for x in parts[1:]]
        if any(x < 0 for x in ticks):
            return None
        return sum(ticks), ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    except (OSError, ValueError, IndexError):
        return None


def _cpu_percent() -> float | None:
    a = _cpu_snapshot()
    if a is None:
        return None
    time.sleep(0.12)
    b = _cpu_snapshot()
    if b is None:
        return None
    total = b[0]-a[0]
    if total <= 0:
        return None
    idle = b[1]-a[1]
    return round(max(0., min(100., (1-idle/total)*100)), 1)


def _meminfo() -> dict | None:
    try:
        vals: dict[str,int] = {}
        with Path('/proc/meminfo').open('r', encoding='ascii') as fp:
            for line in fp:
                key, sep, rest = line.partition(':')
                if sep and key in ('MemTotal','MemAvailable'):
                    match = re.fullmatch(r'\s*(\d+)\s+kB\s*',rest)
                    if match: vals[key] = int(match.group(1))*1024
        total=vals.get('MemTotal',0)
        available=vals.get('MemAvailable',-1)
        if not total or not (0 <= available <= total): return None
        return {'total_bytes':total,'used_bytes':total-available,
                'available_bytes':available,'used_percent':round(100*(total-available)/total,1)}
    except (OSError, ValueError):
        return None


def _disk(label: str, path: Path) -> dict:
    # Strict fixed sources from application configuration, not owner-supplied API params.
    try:
        target = path if path.is_dir() else path.parent
        size = shutil.disk_usage(target)
        return {'label':label,'mount_path':str(target.resolve()),'total_bytes':size.total,
                'used_bytes':size.used,'free_bytes':size.free,
                'used_percent':round(100*size.used/size.total,1) if size.total else None}
    except (OSError, ValueError, ZeroDivisionError):
        return {'label':label,'mount_path':str(path),'total_bytes':None,
                'used_bytes':None,'free_bytes':None,'used_percent':None}


def _gpu_info() -> dict:
    # NVIDIA-specific local measurement. Other accelerators are explicitly not claimed.
    program=shutil.which('nvidia-smi')
    if not program or not Path(program).is_file():
        return {'state':'unavailable','backend':'nvidia-smi','devices':[],
                'note':'nvidia-smi is not installed on the API host; no GPU utilization is claimed'}
    args=[program,'--query-gpu=index,name,utilization.gpu,memory.used,memory.total',
          '--format=csv,noheader,nounits']
    try:
        response=subprocess.run(args,stdin=subprocess.DEVNULL,capture_output=True,text=True,
                                timeout=2,check=False)
        if response.returncode != 0 or len(response.stdout)>LIMIT_BYTES:
            raise ValueError('Driver query did not succeed')
        devices=[]
        for line in response.stdout.splitlines()[:16]:
            fields=[x.strip() for x in line.split(',')]
            if len(fields)!=5: raise ValueError('Unexpected GPU output shape')
            index,name,util,used,total=fields
            if not index.isdecimal() or not re.fullmatch(r'[\w .+()/-]{1,96}',name):
                raise ValueError('Unexpected GPU identifier')
            used_mib=int(used);total_mib=int(total)
            utilization=float(util)
            if not 0<=used_mib<=total_mib or total_mib<=0 or not 0<=utilization<=100:
                raise ValueError('Invalid GPU measurement')
            devices.append({'index':int(index),'name':name,'gpu_percent':round(utilization,1),
                            'memory_used_bytes':used_mib*1048576,
                            'memory_total_bytes':total_mib*1048576,
                            'memory_percent':round(100*used_mib/total_mib,1)})
        if not devices: raise ValueError('Empty GPU result')
        return {'state':'measured','backend':'nvidia-smi','devices':devices,
                'note':'Local API-host NVIDIA devices only; remote inference GPUs are not included'}
    except (OSError,subprocess.TimeoutExpired,ValueError,OverflowError):
        return {'state':'unavailable','backend':'nvidia-smi','devices':[],
                'note':'Local NVIDIA GPU metrics unavailable; driver or query may be unsupported'}


def collect_host_telemetry(workspace:Path, work_root:Path) -> dict:
    cpus=os.cpu_count()
    volumes=[_disk('Configured workspace storage',workspace), _disk('Native Work storage',work_root)]
    # Retain distinct logical stores even if their volumes share an underlying mount.
    return {'sampled_at':datetime.now(UTC).isoformat(),
            'source':{'role':'api_host','hostname':socket.gethostname()[:80],
                      'scope':'OS measurements taken on the machine running MioAgent API'},
            'cpu':{'percent':_cpu_percent(),'logical_cores':cpus if cpus and cpus>0 else None,
                   'measurement':'/proc/stat delta over 120 ms'},
            'memory':_meminfo(), 'volumes':volumes, 'gpu':_gpu_info(),
            'disclaimer':'Metrics are not remote agent, model, browser or ComfyUI-host measurements'}


def register_system_telemetry_routes(app:FastAPI, require_token:Callable, settings:Settings) -> None:
    @app.get('/api/system/telemetry', dependencies=[Depends(require_token)])
    def system_telemetry():
        return collect_host_telemetry(Path(settings.mio_workspace_root),RUNTIME/'work')
