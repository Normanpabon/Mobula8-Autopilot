# Benchmark local de YOLO26

Instalar `requirements-yolo.txt` y usar un clip propio de la misma fuente que se quiere evaluar. Los clips y resultados son datos locales y están ignorados por Git.

```bash
python scripts/benchmark_vision.py benchmarks/analog_reference.mp4 --frames 300 --output benchmarks/analog_results.json
python scripts/benchmark_vision.py benchmarks/digital_reference.mp4 --frames 300 --output benchmarks/digital_results.json
```

La matriz compara YOLO26n DETECT a 416 y 640 con YOLO26n-seg SEGMENT a 416 y 640. El resultado guarda hash del clip, entorno, carga del modelo, p50/p95 de inferencia y pipeline, FPS, CPU y RAM. No mide transporte WebRTC, edad de presentación ni calidad de detección. Para precision, recall o mAP se necesita un conjunto anotado independiente.

`smoke_cpu.json` y los pesos YOLOv8 pertenecían a una comparación histórica y se retiraron de la alfa. El benchmark actual debe ejecutarse con clips de campo antes de seleccionar el modo operativo.
