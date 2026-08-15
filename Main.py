import cv2
import time
import csv
import os
import threading
from collections import deque
from datetime import datetime

try:
    import psutil
except ImportError:
    raise SystemExit(
        "Biblioteca 'psutil' não encontrada. Instale com: pip install psutil"
    )

# ---------------- Configurações ----------------
BUFFER_SECONDS = 30
FPS = 30
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
MAX_FRAMES = BUFFER_SECONDS * FPS

PASTA_VIDEOS = "gravacoes"
PASTA_METRICAS = "metricas"
INTERVALO_AMOSTRAGEM_METRICAS = 1.0  # segundos entre leituras de CPU/RAM

os.makedirs(PASTA_VIDEOS, exist_ok=True)
os.makedirs(PASTA_METRICAS, exist_ok=True)

# ------------------------------------------------

frame_buffer = deque(maxlen=MAX_FRAMES)

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

if not cap.isOpened():
    raise SystemExit("[ERRO] Não foi possível acessar a webcam.")

# Arquivos de log de métricas (CSV), um por execução
timestamp_execucao = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_SISTEMA = os.path.join(PASTA_METRICAS, f"sistema_{timestamp_execucao}.csv")
CSV_EVENTOS = os.path.join(PASTA_METRICAS, f"eventos_{timestamp_execucao}.csv")

with open(CSV_SISTEMA, "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerow(
        ["timestamp", "cpu_percent", "ram_percent", "ram_mb", "fps_real", "frames_no_buffer"]
    )

with open(CSV_EVENTOS, "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerow(
        ["timestamp_evento", "arquivo", "qtd_frames", "duracao_video_s",
         "latencia_gravacao_s", "frames_perdidos_estimado"]
    )

# Contadores globais protegidos por lock simples (uso leve, não crítico)
contador_frames_capturados = 0
contador_frames_perdidos = 0
lock_contadores = threading.Lock()

parar_evento = threading.Event()


def salvar_video(frames, timestamp_evento):
    """
    Salva os frames recebidos como .avi em PASTA_VIDEOS e registra métricas
    do evento (latência, quantidade de frames, frames perdidos estimados) no CSV.
    """
    inicio = time.time()

    nome_arquivo = f"video_{timestamp_evento}.avi"
    caminho_arquivo = os.path.join(PASTA_VIDEOS, nome_arquivo)

    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out = cv2.VideoWriter(caminho_arquivo, fourcc, FPS, (FRAME_WIDTH, FRAME_HEIGHT))

    for f in frames:
        out.write(f)
    out.release()

    fim = time.time()
    latencia = fim - inicio
    duracao_video = len(frames) / FPS if FPS else 0

    with lock_contadores:
        perdidos = contador_frames_perdidos

    with open(CSV_EVENTOS, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(
            [timestamp_evento, nome_arquivo, len(frames),
             round(duracao_video, 3), round(latencia, 3), perdidos]
        )

    print(f"[OK] Vídeo salvo: {caminho_arquivo}")
    print(f"     Frames: {len(frames)} | Duração: {duracao_video:.2f}s | "
          f"Latência de gravação: {latencia:.3f}s")


def monitor_sistema():
    """
    Thread separada: a cada INTERVALO_AMOSTRAGEM_METRICAS segundos, registra
    uso de CPU, RAM e FPS real do loop de captura no CSV de sistema.
    """
    global contador_frames_capturados

    processo = psutil.Process(os.getpid())
    ultimo_contador = 0

    while not parar_evento.is_set():
        time.sleep(INTERVALO_AMOSTRAGEM_METRICAS)

        cpu = psutil.cpu_percent(interval=None)
        ram_percent = processo.memory_percent()
        ram_mb = processo.memory_info().rss / (1024 * 1024)

        with lock_contadores:
            atual = contador_frames_capturados
        fps_real = (atual - ultimo_contador) / INTERVALO_AMOSTRAGEM_METRICAS
        ultimo_contador = atual

        with open(CSV_SISTEMA, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 round(cpu, 1), round(ram_percent, 2), round(ram_mb, 1),
                 round(fps_real, 1), len(frame_buffer)]
            )

        print(f"[METRICAS] CPU: {cpu:.1f}% | RAM: {ram_mb:.1f}MB "
              f"({ram_percent:.1f}%) | FPS real: {fps_real:.1f} | "
              f"Buffer: {len(frame_buffer)}/{MAX_FRAMES}")


print("Gravando... Pressione 's' para salvar os últimos 30s. Pressione 'q' para sair.")
print(f"[INFO] Vídeos serão salvos em: ./{PASTA_VIDEOS}/")
print(f"[INFO] Métricas serão salvas em: ./{PASTA_METRICAS}/")

thread_monitor = threading.Thread(target=monitor_sistema, daemon=True)
thread_monitor.start()

intervalo_esperado = 1.0 / FPS

try:
    ultimo_tempo_frame = time.time()
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Erro ao acessar webcam")
            break

        agora = time.time()
        # Estima frames perdidos: se o intervalo entre leituras foi maior que
        # o esperado, provavelmente frames foram descartados pelo driver/SO.
        intervalo_real = agora - ultimo_tempo_frame
        if intervalo_real > intervalo_esperado * 1.5:
            perdidos_estimados = int(intervalo_real / intervalo_esperado) - 1
            if perdidos_estimados > 0:
                with lock_contadores:
                    contador_frames_perdidos += perdidos_estimados
        ultimo_tempo_frame = agora

        frame_buffer.append(frame)

        with lock_contadores:
            contador_frames_capturados += 1

        cv2.imshow("Webcam", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            print("Saindo...")
            break
        elif key == ord('s'):
            print("Salvando...")
            timestamp_evento = datetime.now().strftime("%Y%m%d_%H%M%S")
            threading.Thread(
                target=salvar_video,
                args=(list(frame_buffer), timestamp_evento)
            ).start()

finally:
    parar_evento.set()
    cap.release()
    cv2.destroyAllWindows()
    print(f"\n[INFO] Execução encerrada. Confira os CSVs em ./{PASTA_METRICAS}/ "
          f"para os dados coletados.")