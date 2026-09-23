# Roadmap después de la alfa

La aceptación pendiente de la versión alfa se registra en [PLAN_ACCION.md](PLAN_ACCION.md). Aquí se enumeran cambios posteriores; ninguno implica una capacidad ya validada con hardware.

## Prioridad inmediata

- Completar la matriz de telemetría, video y grabación con TX12, EasyCap/Cobra X y Mobula8 reales.
- Medir y corregir latencia de captura a navegador, color y estabilidad de video. Aislar la captura en un proceso si el driver puede bloquear `read()`.
- Medir el impacto de YOLO26 sobre WebRTC y grabación; decidir modo y tamaño de inferencia adecuados para el equipo objetivo.
- Identificar una ruta de entrada RC soportada por EdgeTX o un adaptador externo; verificar canales en Betaflight sin hélices y fallos seguros antes de considerar uso de campo.

## Mejoras posteriores

- Manifiesto por toma con tiempos de captura y relación explícita con el JSON de sesión; descarga y verificación automática de MP4.
- Calibración de imagen por capturadora y comparación con una referencia de color.
- Dataset propio etiquetado para medir precision, recall y mAP de YOLO26; entrenar o exportar modelos solo después de tener el baseline de campo.
- Exportación CSV, comparación entre sesiones y alertas configurables de batería y enlace.
- Autenticación para uso en redes no confiables.

El vuelo autónomo depende de una ruta RC física validada, telemetría fiable, latencia medida y un diseño de seguridad independiente del proceso de la estación. No forma parte de la alfa.
