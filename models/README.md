# Modelos de visión

Pesos predeterminados: `yolo26n.pt` (detect) y `yolo26n-seg.pt` (segment).
Colocarlos aquí para uso offline. Los pesos no se versionan; Ultralytics puede
descargar los nombres oficiales si no existen localmente.

Para un modelo propio, configurar `models.detect` o `models.segment` con su
ruta/nombre, y cambiar `coco_classes.enabled` y `confidence.per_class` a nombres
que existan en `model.names`. El nombre histórico `coco_classes` no limita el
pipeline a COCO. Se comprueba la tarea real del modelo. La lista de modelos
locales usa `-seg` como convención de descubrimiento; la carga explícita no
requiere ese sufijo. Exportaciones ONNX/engine deben llevar metadata de tarea
y clases compatible con Ultralytics; no se han validado en esta migración.
