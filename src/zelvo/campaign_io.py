"""Durable experiment storage and local resource measurements, without paid services."""
from contextlib import contextmanager
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

from zelvo.simulation.smoke import atomic_json,sha256


def save(path,data):
    atomic_json(Path(path),json.dumps(data,indent=2,allow_nan=False)+'\n')


def read(path):
    path=Path(path)
    opener=gzip.open if path.suffix=='.gz' else open
    with opener(path,'rt',encoding='utf-8') as stream:return json.load(stream)


def lines(path):
    path=Path(path)
    opener=gzip.open if path.suffix=='.gz' else open
    with opener(path,'rt',encoding='utf-8') as stream:
        for line in stream:
            if line.strip():yield json.loads(line)


def engine_hash(directory):
    digest=hashlib.sha256()
    for path in sorted(Path(directory).rglob('*.py')):
        digest.update(path.relative_to(directory).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


@contextmanager
def exclusive(path,blocking=False):
    """OS lock released on process exit; a file's mere presence is not a lock."""
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    stream=path.open('a+b')
    stream.seek(0,2)
    if stream.tell()==0:stream.write(b'0');stream.flush()
    stream.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|(0 if blocking else fcntl.LOCK_NB))
    except OSError:
        stream.close()
        raise RuntimeError('Another process holds '+str(path)) from None
    try:yield
    finally:
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_UN)
        stream.close()


def process_alive(pid):
    if not pid:return False
    if os.name=='nt':
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x100000,False,int(pid))
        if not handle:return ctypes.get_last_error()==5  # Access denied means do not presume dead.
        try:return kernel.WaitForSingleObject(ctypes.c_void_p(handle),0)==258
        finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    try:os.kill(int(pid),0);return True
    except ProcessLookupError:return False
    except PermissionError:return True


def resources(directory,pid=None):
    data={'disk_free_bytes':shutil.disk_usage(directory).free,'available_memory_bytes':None,'peak_rss_bytes':None}
    if os.name=='nt':
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[(k,ctypes.c_ulonglong) for k in
                ('total','available','total_page','available_page','total_virtual','available_virtual','extended')]
        memory=Memory();memory.length=ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            data['available_memory_bytes']=memory.available
        class Counters(ctypes.Structure):
            _fields_=[('size',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(k,ctypes.c_size_t) for k in
                ('peak','working','peak_pool_paged','pool_paged','peak_pool_nonpaged','pool_nonpaged','page','peak_page')]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.restype=ctypes.c_void_p
        handle=kernel.OpenProcess(0x410,False,pid or os.getpid())
        if handle:
            try:
                counters=Counters();counters.size=ctypes.sizeof(counters)
                if ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(handle),ctypes.byref(counters),counters.size):
                    data['peak_rss_bytes']=counters.peak
            finally:kernel.CloseHandle(ctypes.c_void_p(handle))
    else:
        try:
            import resource
            if pid in (None,os.getpid()):data['peak_rss_bytes']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
            for line in Path('/proc/meminfo').read_text().splitlines():
                if line.startswith('MemAvailable:'):data['available_memory_bytes']=int(line.split()[1])*1024
        except (ImportError,OSError):pass
    return data


def compress_result(path):
    """Verify lossless archives, atomically publish references, then remove originals."""
    path=Path(path).resolve()
    result=read(path)
    archives={}
    remove=[]
    for key,filename in result['artifacts'].items():
        original=Path(filename).resolve()
        if original.parent!=path.parent or key in ('result','config') or not original.is_file() or original.suffix=='.gz':continue
        digest=sha256(original)
        target=original.with_name(original.name+'.gz')
        temporary=target.with_name(target.name+'.tmp')
        with original.open('rb') as source,gzip.open(temporary,'wb',compresslevel=3) as destination:
            shutil.copyfileobj(source,destination)
        check=hashlib.sha256()
        with gzip.open(temporary,'rb') as stream:
            while block:=stream.read(1024*1024):check.update(block)
        if check.hexdigest()!=digest:raise ValueError('Archive integrity mismatch')
        temporary.replace(target)
        result['artifacts'][key]=str(target)
        archives[key]={'uncompressed_sha256':digest,'original_bytes':original.stat().st_size,'compressed_bytes':target.stat().st_size}
        remove.append(original)
    result.setdefault('archive_integrity',{}).update(archives)
    save(path,result)
    for original in remove:original.unlink()
    return result


def prediction_quality(result):
    """Join forecasts to observed evaluation labels; never fill censored targets."""
    predictions={(r['time'],r['vehicle'],r['tls'],r['link']):r for r in lines(result['artifacts']['predictions'])}
    count=censored=queue_count=covered=interval_count=0
    analytic_error=forecast_error=queue_error=persistence_error=0.0
    for label in lines(result['artifacts']['training']):
        prediction=predictions.get((label['time'],label['vehicle'],label['tls'],label['link']))
        if prediction is None:continue
        if label['censored'] or label['eta_residual'] is None:censored+=1
        else:
            actual=label['analytical_eta']+label['eta_residual']
            count+=1
            analytic_error+=abs(actual-prediction['analytical_eta'])
            forecast_error+=abs(actual-prediction['eta'])
            limits=prediction.get('arrival_window_s')
            if limits:
                interval_count+=1
                covered+=limits[0]<=actual<=limits[1]
        if label['queue_10s'] is not None and prediction.get('queue_prediction') is not None:
            queue_count+=1
            queue_error+=abs(label['queue_10s']-prediction['queue_prediction'])
            persistence_error+=abs(label['queue_10s']-label['features'][3])
    return {'labelled_eta_count':count,'censored_eta_count':censored,
        'analytical_absolute_error_sum_s':analytic_error,'forecast_absolute_error_sum_s':forecast_error,
        'interval_count':interval_count,'interval_covered_count':covered,'labelled_queue_count':queue_count,
        'queue_absolute_error_sum':queue_error,'persistence_absolute_error_sum':persistence_error,
        'note':'Observed-policy forecast accuracy, conditional on observed labels; not causal AI benefit or independent samples'}
