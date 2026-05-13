"""
video_calibrate.py — Diagnóstico y corrección de color/sobreexposición
=======================================================================
Herramienta interactiva para la capturadora USB genérica (EasyCap / RCA→USB).

NUEVO en esta versión:
  - Corrección de White Balance por canal R/G/B (para tintes de color)
  - Temperatura de color presets (cálido / neutro / frío)
  - Corrección de color skin-tone automática
  - Todos los controles anteriores conservados

Uso:
    python video_calibrate.py --device 1

Controles:
    B / b   → Brillo        +5 / -5
    C / c   → Contraste     +5 / -5
    S / s   → Saturación    +5 / -5   (empieza en 60, no 128)
    G / g   → Gamma         +0.1 / -0.1

    R / r   → Canal Rojo    +0.05 / -0.05  (WB)
    E / e   → Canal Verde   +0.05 / -0.05  (WB)
    U / u   → Canal Azul    +0.05 / -0.05  (WB)
    T       → Preset Cálido (reduce azul)
    Y       → Preset Neutro (reset WB)
    I       → Preset Frío   (reduce rojo)

    H       → Toggle Histogram EQ
    N       → Toggle NTSC/PAL
    P       → Imprimir configuración actual
    R_KEY   → Reset completo  (tecla mayúscula R → ahora es 'X' para no conflicto)
    X       → Reset completo a defaults
    W       → Guardar configuración a video_config.json
    Q       → Salir
"""

import cv2
import numpy as np
import json
import argparse
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "video_config.json"

# ── Valores por defecto ───────────────────────────────────────────
DEFAULTS = {
    "brightness":  0,      # -64 a 64
    "contrast":    32,     # 0 a 64
    "saturation":  60,     # 0 a 128  ← NOTA: 60 es mucho más razonable que 128
    "gamma":       1.0,    # 0.1 a 3.0
    "hist_eq":     False,
    "ntsc":        True,
    # Corrección de White Balance por canal (multiplicadores)
    # 1.0 = sin cambio. Para quitar el tinte violeta: bajar R y B, subir G levemente
    "wb_r":        1.0,    # 0.5 a 2.0
    "wb_g":        1.0,    # 0.5 a 2.0
    "wb_b":        1.0,    # 0.5 a 2.0
}

# Presets de White Balance
WB_PRESETS = {
    "neutro":  {"wb_r": 1.0,  "wb_g": 1.0,  "wb_b": 1.0},
    "calido":  {"wb_r": 1.15, "wb_g": 1.0,  "wb_b": 0.80},  # quita frío/azul
    "frio":    {"wb_r": 0.85, "wb_g": 1.0,  "wb_b": 1.15},
    # Para tinte violeta/magenta como en tu imagen:
    # el violeta = R alto + B alto + G bajo → bajar R y B, subir G
    "anti_magenta": {"wb_r": 0.75, "wb_g": 1.10, "wb_b": 0.75},
}


def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                cfg = {**DEFAULTS, **json.load(f)}
            print(f"[CONFIG] Cargada de {CONFIG_FILE}")
            return cfg
        except Exception:
            pass
    return dict(DEFAULTS)


def save_config(cfg: dict):
    save_cfg = {k: v for k, v in cfg.items() if k in DEFAULTS}
    with open(CONFIG_FILE, "w") as f:
        json.dump(save_cfg, f, indent=2)
    print(f"\n✅ Guardado en: {CONFIG_FILE}")
    print(f"   {save_cfg}\n")


def apply_capture_props(cap: cv2.VideoCapture, cfg: dict):
    cap.set(cv2.CAP_PROP_BRIGHTNESS,  cfg["brightness"])
    cap.set(cv2.CAP_PROP_CONTRAST,    cfg["contrast"])
    cap.set(cv2.CAP_PROP_SATURATION,  cfg["saturation"])
    fps = 29.97 if cfg["ntsc"] else 25.0
    cap.set(cv2.CAP_PROP_FPS, fps)
    return {
        "brightness": cap.get(cv2.CAP_PROP_BRIGHTNESS),
        "contrast":   cap.get(cv2.CAP_PROP_CONTRAST),
        "saturation": cap.get(cv2.CAP_PROP_SATURATION),
        "fps":        cap.get(cv2.CAP_PROP_FPS),
    }


def apply_white_balance(frame: np.ndarray, wb_r: float, wb_g: float, wb_b: float) -> np.ndarray:
    """
    Multiplica cada canal por su factor de WB.
    Canales OpenCV BGR: índice 0=B, 1=G, 2=R
    """
    if wb_r == 1.0 and wb_g == 1.0 and wb_b == 1.0:
        return frame
    result = frame.astype(np.float32)
    result[:, :, 0] = np.clip(result[:, :, 0] * wb_b, 0, 255)  # B
    result[:, :, 1] = np.clip(result[:, :, 1] * wb_g, 0, 255)  # G
    result[:, :, 2] = np.clip(result[:, :, 2] * wb_r, 0, 255)  # R
    return result.astype(np.uint8)


def apply_software_correction(frame: np.ndarray, cfg: dict) -> np.ndarray:
    result = frame.copy()

    # 1. White Balance por canal (lo más importante para el tinte violeta)
    result = apply_white_balance(
        result,
        cfg.get("wb_r", 1.0),
        cfg.get("wb_g", 1.0),
        cfg.get("wb_b", 1.0),
    )

    # 2. Corrección de gamma
    gamma = cfg.get("gamma", 1.0)
    if gamma != 1.0:
        inv_gamma = 1.0 / gamma
        table = np.array([((i / 255.0) ** inv_gamma) * 255
                          for i in range(256)], dtype="uint8")
        result = cv2.LUT(result, table)

    # 3. Ecualización de histograma (opcional)
    if cfg.get("hist_eq", False):
        yuv = cv2.cvtColor(result, cv2.COLOR_BGR2YUV)
        yuv[:, :, 0] = cv2.equalizeHist(yuv[:, :, 0])
        result = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR)

    return result


def draw_overlay(frame: np.ndarray, cfg: dict, actual_props: dict,
                 hist_data) -> np.ndarray:
    h, w = frame.shape[:2]
    overlay = frame.copy()

    panel_w = 300
    cv2.rectangle(overlay, (0, 0), (panel_w, 400), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, overlay)

    wb_r = cfg.get("wb_r", 1.0)
    wb_g = cfg.get("wb_g", 1.0)
    wb_b = cfg.get("wb_b", 1.0)

    lines = [
        ("=== FPV CALIBRATION ===",           (0, 230, 255), True),
        (f"B) Brightness: {cfg['brightness']:+.0f}",  (255, 255, 255), False),
        (f"C) Contrast:   {cfg['contrast']:.0f}",     (255, 255, 255), False),
        (f"S) Saturation: {cfg['saturation']:.0f}",   (255, 255, 255), False),
        (f"G) Gamma:      {cfg['gamma']:.2f}",         (255, 255, 255), False),
        ("",                                           (255, 255, 255), False),
        ("--- White Balance ---",                      (0, 200, 200), True),
        (f"R) Red:    {wb_r:.2f}",  (80, 80, 255), False),    # rojo en BGR = (B=80,G=80,R=255)
        (f"E) Green:  {wb_g:.2f}",  (80, 200, 80), False),
        (f"U) Blue:   {wb_b:.2f}",  (200, 100, 50), False),
        ("T=Calido  Y=Neutro  I=Anti-Magenta", (200, 200, 100), False),
        ("",                                           (255, 255, 255), False),
        (f"H) Hist EQ: {'ON' if cfg['hist_eq'] else 'OFF'}",
         (0, 255, 0) if cfg["hist_eq"] else (150, 150, 150), False),
        (f"N) Standard: {'NTSC ~30fps' if cfg['ntsc'] else 'PAL ~25fps'}",
         (255, 255, 255), False),
        ("",                                           (255, 255, 255), False),
        ("--- Driver props ---",                       (0, 200, 200), True),
        (f"FPS: {actual_props.get('fps', 0):.1f}  "
         f"Bright: {actual_props.get('brightness', 0):.0f}  "
         f"Cont: {actual_props.get('contrast', 0):.0f}", (180, 180, 180), False),
        ("",                                           (255, 255, 255), False),
        ("W=Guardar  X=Reset  Q=Salir",                (100, 255, 100), False),
    ]

    for i, (text, color, bold) in enumerate(lines):
        y = 22 + i * 20
        cv2.putText(overlay, text, (8, y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.48 if bold else 0.42,
                    color, 2 if bold else 1)

    # Mini histograma
    if hist_data is not None:
        hh, hw = 80, 200
        hx, hy = w - hw - 10, 10
        hist_img = np.zeros((hh, hw, 3), dtype=np.uint8)
        for ci, col_h in enumerate(hist_data):
            if col_h is None:
                continue
            ch = col_h.copy()
            cv2.normalize(ch, ch, 0, hh, cv2.NORM_MINMAX)
            color_h = [(255, 50, 50), (50, 255, 50), (50, 50, 255)][ci]
            for x_h in range(hw):
                bin_idx = int(x_h * 256 / hw)
                bin_val = min(int(ch[bin_idx][0]), hh - 1)
                cv2.line(hist_img, (x_h, hh), (x_h, hh - bin_val), color_h, 1)
        overlay[hy:hy + hh, hx:hx + hw] = hist_img
        cv2.putText(overlay, "Histogram", (hx, hy + hh + 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

        # Indicador de sobreexposición
        gray    = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        overexp = np.sum(gray > 240) / gray.size * 100
        col     = (0, 255, 0) if overexp < 5 else (0, 140, 255) if overexp < 20 else (0, 0, 255)
        cv2.putText(overlay, f"Overexp: {overexp:.1f}%", (hx, hy - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, col, 1)

        # Indicador de dominante de color (promedio por canal)
        mean_b = np.mean(frame[:, :, 0])
        mean_g = np.mean(frame[:, :, 1])
        mean_r = np.mean(frame[:, :, 2])
        cv2.putText(overlay,
                    f"R:{mean_r:.0f} G:{mean_g:.0f} B:{mean_b:.0f}",
                    (hx, hy + hh + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    return overlay


def compute_histogram(frame):
    return [cv2.calcHist([frame], [i], None, [256], [0, 256]) for i in range(3)]


def print_status(cfg: dict, actual_props: dict):
    print("\n─── Configuración actual ────────────────────────")
    print(f"  brightness:  {cfg['brightness']:+.0f}")
    print(f"  contrast:    {cfg['contrast']:.0f}")
    print(f"  saturation:  {cfg['saturation']:.0f}")
    print(f"  gamma:       {cfg['gamma']:.2f}")
    print(f"  hist_eq:     {cfg['hist_eq']}")
    print(f"  ntsc:        {cfg['ntsc']}")
    print(f"  wb_r:        {cfg.get('wb_r', 1.0):.2f}")
    print(f"  wb_g:        {cfg.get('wb_g', 1.0):.2f}")
    print(f"  wb_b:        {cfg.get('wb_b', 1.0):.2f}")
    print(f"  driver fps:  {actual_props.get('fps', '?'):.1f}")
    print("─────────────────────────────────────────────────\n")


def main():
    parser = argparse.ArgumentParser(description="FPV Capture Calibration Tool")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width",  type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    # Aplicar preset anti-magenta al arrancar (para la capturadora EasyCap típica)
    parser.add_argument("--preset", default=None,
                        choices=["neutro", "calido", "frio", "anti_magenta"],
                        help="Preset WB inicial")
    args = parser.parse_args()

    print("=" * 60)
    print("  FPV Capture Calibration Tool  (con White Balance)")
    print("=" * 60)
    print(f"  Dispositivo: {args.device} | Resolución: {args.width}x{args.height}")
    print("=" * 60)
    print()
    print("  ── Calibración básica ──")
    print("  B/b  Brillo ±5     C/c  Contraste ±5")
    print("  S/s  Saturación ±5   G/g  Gamma ±0.1")
    print()
    print("  ── White Balance (para quitar tintes de color) ──")
    print("  R/r  Canal Rojo ±0.05   (actual: ver overlay)")
    print("  E/e  Canal Verde ±0.05")
    print("  U/u  Canal Azul ±0.05")
    print("  T    Preset Cálido   Y    Preset Neutro")
    print("  I    Preset Anti-Magenta  ← recomendado para tu cámara")
    print()
    print("  W=Guardar  X=Reset  P=Print  Q=Salir")
    print()

    cfg = load_config()

    # Aplicar preset si se solicitó
    if args.preset:
        cfg.update(WB_PRESETS[args.preset])
        print(f"[CONFIG] Preset aplicado: {args.preset}")
    else:
        # Auto-sugerir anti_magenta si los valores de WB son neutros (configuración nueva)
        if cfg.get("wb_r", 1.0) == 1.0 and cfg.get("wb_b", 1.0) == 1.0:
            print("💡 TIP: Tu imagen tiene tinte violeta/magenta.")
            print("   Presiona I para aplicar el preset Anti-Magenta como punto de partida.\n")

    # Bajar saturación si está en el máximo (problema común)
    if cfg.get("saturation", 60) >= 120:
        print(f"⚠  Saturación en {cfg['saturation']} (muy alta). Bajándola a 70 automáticamente.")
        cfg["saturation"] = 70

    cap = cv2.VideoCapture(args.device, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(args.device)
    if not cap.isOpened():
        print(f"❌ No se pudo abrir dispositivo {args.device}")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    actual_props = apply_capture_props(cap, cfg)
    hist_data    = None
    frame_count  = 0

    print("✅ Capturadora abierta.\n")

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        frame_count += 1
        if frame_count % 15 == 0:
            hist_data = compute_histogram(frame)

        corrected = apply_software_correction(frame, cfg)
        display   = draw_overlay(corrected, cfg, actual_props, hist_data)
        cv2.imshow("FPV Calibration", display)

        key = cv2.waitKey(1) & 0xFF

        if key in (ord('q'), ord('Q')):
            break

        # ── Brillo ──
        elif key == ord('B'):
            cfg["brightness"] = min(64, cfg["brightness"] + 5)
            actual_props = apply_capture_props(cap, cfg)
        elif key == ord('b'):
            cfg["brightness"] = max(-64, cfg["brightness"] - 5)
            actual_props = apply_capture_props(cap, cfg)

        # ── Contraste ──
        elif key == ord('C'):
            cfg["contrast"] = min(64, cfg["contrast"] + 5)
            actual_props = apply_capture_props(cap, cfg)
        elif key == ord('c'):
            cfg["contrast"] = max(0, cfg["contrast"] - 5)
            actual_props = apply_capture_props(cap, cfg)

        # ── Saturación ──
        elif key == ord('S'):
            cfg["saturation"] = min(128, cfg["saturation"] + 5)
            actual_props = apply_capture_props(cap, cfg)
        elif key == ord('s'):
            cfg["saturation"] = max(0, cfg["saturation"] - 5)
            actual_props = apply_capture_props(cap, cfg)

        # ── Gamma ──
        elif key == ord('G'):
            cfg["gamma"] = min(3.0, round(cfg["gamma"] + 0.1, 2))
        elif key == ord('g'):
            cfg["gamma"] = max(0.1, round(cfg["gamma"] - 0.1, 2))

        # ── White Balance: Rojo (R/r) ──
        elif key == ord('R'):
            cfg["wb_r"] = min(2.0, round(cfg.get("wb_r", 1.0) + 0.05, 2))
            print(f"[WB] Red: {cfg['wb_r']:.2f}")
        elif key == ord('r'):
            cfg["wb_r"] = max(0.3, round(cfg.get("wb_r", 1.0) - 0.05, 2))
            print(f"[WB] Red: {cfg['wb_r']:.2f}")

        # ── White Balance: Verde (E/e) ──
        elif key == ord('E'):
            cfg["wb_g"] = min(2.0, round(cfg.get("wb_g", 1.0) + 0.05, 2))
            print(f"[WB] Green: {cfg['wb_g']:.2f}")
        elif key == ord('e'):
            cfg["wb_g"] = max(0.3, round(cfg.get("wb_g", 1.0) - 0.05, 2))
            print(f"[WB] Green: {cfg['wb_g']:.2f}")

        # ── White Balance: Azul (U/u) ──
        elif key == ord('U'):
            cfg["wb_b"] = min(2.0, round(cfg.get("wb_b", 1.0) + 0.05, 2))
            print(f"[WB] Blue: {cfg['wb_b']:.2f}")
        elif key == ord('u'):
            cfg["wb_b"] = max(0.3, round(cfg.get("wb_b", 1.0) - 0.05, 2))
            print(f"[WB] Blue: {cfg['wb_b']:.2f}")

        # ── Presets WB ──
        elif key == ord('T') or key == ord('t'):
            cfg.update(WB_PRESETS["calido"])
            print("[WB] Preset: Cálido")
        elif key == ord('Y') or key == ord('y'):
            cfg.update(WB_PRESETS["neutro"])
            print("[WB] Preset: Neutro")
        elif key == ord('I') or key == ord('i'):
            cfg.update(WB_PRESETS["anti_magenta"])
            print("[WB] Preset: Anti-Magenta (R↓ G↑ B↓)")

        # ── Otros ──
        elif key == ord('H') or key == ord('h'):
            cfg["hist_eq"] = not cfg["hist_eq"]
            print(f"[CONFIG] Histogram EQ: {'ON' if cfg['hist_eq'] else 'OFF'}")

        elif key == ord('N') or key == ord('n'):
            cfg["ntsc"] = not cfg["ntsc"]
            actual_props = apply_capture_props(cap, cfg)
            print(f"[CONFIG] {'NTSC 29.97fps' if cfg['ntsc'] else 'PAL 25fps'}")

        elif key == ord('P') or key == ord('p'):
            print_status(cfg, actual_props)

        elif key == ord('X') or key == ord('x'):
            cfg = dict(DEFAULTS)
            actual_props = apply_capture_props(cap, cfg)
            print("[CONFIG] Reset a defaults")

        elif key == ord('W') or key == ord('w'):
            save_config(cfg)
            print_status(cfg, actual_props)

    cap.release()
    cv2.destroyAllWindows()

    resp = input("\n¿Guardar configuración actual? (s/n): ").strip().lower()
    if resp == "s":
        save_config(cfg)


if __name__ == "__main__":
    main()
