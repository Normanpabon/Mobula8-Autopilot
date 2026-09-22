#!/usr/bin/env python3
"""Replay the same clip/frames for six models. Never infer accuracy from unlabelled video."""
import argparse
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
import cv2
import numpy as np
import psutil
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from vision_config import VisionConfig
from vision_pipeline import VisionPipeline

MATRIX = [('yolov8n.pt','detect',640), ('yolov8n.pt','detect',416),
          ('yolo26n.pt','detect',640), ('yolo26n.pt','detect',416),
          ('yolo26n-seg.pt','segment',416), ('yolo26n-seg.pt','segment',640)]

def percentiles(values):
    return {'p50': float(np.percentile(values,50)), 'p95': float(np.percentile(values,95))}

def benchmark(source, limit, config_path):
    import ultralytics
    import torch
    import tempfile
    config = VisionConfig.load(config_path)
    rows=[]
    for name, mode, size in MATRIX:
        # Same ROI (whole frame), classes and confidence for all candidates.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            cfg = config.patched({'pipeline_mode':mode,'models':{mode:name},'imgsz':{mode:size}})
            cfg.save(path/'vision.json')
            pipeline = VisionPipeline(path/'roi.json',path/'vision.json')
            pipeline.set_roi([True]*96)
            try:
                pipeline.model.load()
                capture=cv2.VideoCapture(str(source))
                if not capture.isOpened():
                    raise ValueError(f'No se pudo abrir {source}')
                inference, timings, cpu, ram = [], [], [], []
                process=psutil.Process()
                process.cpu_percent()
                started=time.perf_counter()
                try:
                    for _ in range(limit):
                        ok,frame=capture.read()
                        if not ok:
                            break
                        result=pipeline._process(frame)
                        inference.append(result.seg_ms+result.det_ms)
                        timings.append(result.pipeline_ms)
                        cpu.append(process.cpu_percent())
                        ram.append(process.memory_info().rss/1024**2)
                finally:
                    capture.release()
                if not inference:
                    raise ValueError('El clip no contiene frames decodificables')
                rows.append({'model':name,'task':mode,'imgsz':size,'frames':len(inference),
                             'model_load_ms':pipeline.model.model_load_ms,'warmup_ms':pipeline.model.warmup_ms,
                             'inference_ms':percentiles(inference),'pipeline_ms':percentiles(timings),
                             'vision_fps':len(inference)/(time.perf_counter()-started),
                             'cpu_percent_mean':float(np.mean(cpu)), 'ram_mb_peak':max(ram),
                             'gpu_percent':None,'vram_mb':None,'result_age_ms':None,
                             'false_positives':None,'false_negatives':None})
            finally:
                pipeline._executor.shutdown()
    return {'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'runtime':{'python':platform.python_version(),'platform':platform.platform(),
                       'ultralytics':ultralytics.__version__,'torch':torch.__version__},
            'config':config.model_dump(),'results':rows,
            'notes':'Offline replay; FPS includes decoding and sampling. CPU is process CPU (may exceed 100%). '
                    'GPU utilization/VRAM and live result age are unmeasured. FP/FN require labelled data. '
                    'pipeline_ms includes ROI and output normalization, not WebRTC/capture transport.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--frames',type=int,default=300)
    parser.add_argument('--config',type=Path,default=Path(__file__).resolve().parents[1]/'backend/config/vision.json')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.frames<1:
        parser.error('--frames debe ser positivo')
    if not args.source.is_file():
        parser.error('El clip no existe')
    output=benchmark(args.source,args.frames,args.config)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,indent=2)+'\n')

if __name__=='__main__':
    main()
