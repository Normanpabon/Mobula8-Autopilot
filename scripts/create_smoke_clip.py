"""Create a deterministic STATIC technical clip, not a field/accuracy benchmark."""
import argparse
from pathlib import Path
import cv2
from ultralytics.utils import ASSETS

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('output',type=Path)
args=parser.parse_args()
frame=cv2.imread(str(ASSETS/'bus.jpg'))
if frame is None:
    raise ValueError('Ultralytics bus.jpg no disponible')
frame=cv2.resize(frame,(480,640))
writer=cv2.VideoWriter(str(args.output),cv2.VideoWriter_fourcc(*'MJPG'),10,(480,640))
if not writer.isOpened():
    raise ValueError('No se pudo abrir el archivo de salida')
try:
    for _ in range(20):
        writer.write(frame)
finally:
    writer.release()
