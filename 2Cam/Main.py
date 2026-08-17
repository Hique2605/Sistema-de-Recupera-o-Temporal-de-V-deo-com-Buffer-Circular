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

# Cada entrada representa uma câmera física conectada ao sistema.
# "id" é usado como sufixo em arquivos e nas colunas de CSV.
# "nome" identifica o ponto de captura (ex.: quadra, ângulo, etc.).
# "index" é o índice do dispositivo passado para cv2.VideoCapture.
#
# Para expandir para múltiplas câmeras/quadras, basta adicionar
# novas entradas nesta lista — nenhuma outra parte do código
# precisa ser alterada.
CAMERAS = [
    {"id": "cam0", "nome": "Quadra Principal", "index": 0},
    # {"id": "cam1", "nome": "Quadra 2 - Lado A", "index": 1},
    # {"id": "cam2", "nome": "Quadra 2 - Lado B", "index": 2},
]

os.makedirs(PASTA_VIDEOS, exist_ok=True)
os.makedirs(PASTA_METRICAS, exist_ok=True)

# ------------------------------------------------

timestamp_execucao = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_SISTEMA = os.path.join(PASTA_METRICAS, f"sistema_{timestamp_execucao}.csv")
CSV_EVENTOS = os.path.join(PASTA_METRICAS, f"eventos_{timestamp_execucao}.csv")

with open(CSV_SISTEMA, "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerow(
        ["timestamp", "camera_id", "cpu_percent", "ram_percent", "ram_mb",
         "fps_real", "frames_no_buffer"]
    )

with open(CSV_EVENTOS, "w", newline="", encoding="utf-8") as f:
    csv.writer(f).writerow(
        ["timestamp_evento", "camera_id", "arquivo", "qtd_frames",
         "duracao_video_s", "latencia_gravacao_s", "frames_perdidos_estimado"]
    )

csv_lock = threading.Lock()  # protege escrita concorrente nos CSVs compartilhados


def registrar_evento(timestamp_evento, camera_id, nome_arquivo, qtd_frames,
                      duracao_video, latencia, perdidos):
    with csv_lock:
        with open(CSV_EVENTOS, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [timestamp_evento, camera_id, nome_arquivo, qtd_frames,
                 round(duracao_video, 3), round(latencia, 3), perdidos]
            )


def registrar_metrica_sistema(camera_id, cpu, ram_percent, ram_mb, fps_real, buffer_len):
    with csv_lock:
        with open(CSV_SISTEMA, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(
                [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), camera_id,
                 round(cpu, 1), round(ram_percent, 2), round(ram_mb, 1),
                 round(fps_real, 1), buffer_len]
            )


class CameraWorker(threading.Thread):
    """
    Responsável por uma única câmera: captura contínua de frames,
    manutenção do buffer circular (janela deslizante) e salvamento
    do trecho armazenado quando um evento é acionado.

    Cada instância é independente — múltiplas câmeras rodam em
    paralelo, cada uma com seu próprio buffer, sua própria janela
    de exibição e seus próprios contadores.
    """

    def __init__(self, camera_id, nome, index, width=FRAME_WIDTH,
                 height=FRAME_HEIGHT, fps=FPS, buffer_seconds=BUFFER_SECONDS):
        super().__init__(daemon=True)
        self.camera_id = camera_id
        self.nome = nome
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self.max_frames = buffer_seconds * fps

        self.buffer = deque(maxlen=self.max_frames)
        self.frame_atual = None

        self.contador_frames_capturados = 0
        self.contador_frames_perdidos = 0
        self.lock = threading.Lock()

        self.parar_evento = threading.Event()

        self.cap = cv2.VideoCapture(self.index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

        if not self.cap.isOpened():
            raise SystemExit(
                f"[ERRO] Não foi possível acessar a câmera '{self.camera_id}' "
                f"(index={self.index})."
            )

    def run(self):
        intervalo_esperado = 1.0 / self.fps
        ultimo_tempo_frame = time.time()

        while not self.parar_evento.is_set():
            ret, frame = self.cap.read()
            if not ret:
                print(f"[ERRO] Falha ao ler frame da câmera '{self.camera_id}'.")
                break

            agora = time.time()
            intervalo_real = agora - ultimo_tempo_frame
            if intervalo_real > intervalo_esperado * 1.5:
                perdidos_estimados = int(intervalo_real / intervalo_esperado) - 1
                if perdidos_estimados > 0:
                    with self.lock:
                        self.contador_frames_perdidos += perdidos_estimados
            ultimo_tempo_frame = agora

            with self.lock:
                self.buffer.append(frame)
                self.contador_frames_capturados += 1
                self.frame_atual = frame

        self.cap.release()

    def snapshot_buffer(self):
        """Retorna uma cópia estável do buffer atual, thread-safe."""
        with self.lock:
            return list(self.buffer)

    def frames_perdidos(self):
        with self.lock:
            return self.contador_frames_perdidos

    def frames_capturados(self):
        with self.lock:
            return self.contador_frames_capturados

    def tamanho_buffer(self):
        with self.lock:
            return len(self.buffer)

    def parar(self):
        self.parar_evento.set()

    def salvar_video(self, timestamp_evento):
        """
        Salva o conteúdo atual do buffer desta câmera como .avi e
        registra as métricas do evento (latência, frames, perdas) no CSV.
        Executado em thread separada para não travar a captura.
        """
        inicio = time.time()
        frames = self.snapshot_buffer()

        nome_arquivo = f"video_{self.camera_id}_{timestamp_evento}.avi"
        caminho_arquivo = os.path.join(PASTA_VIDEOS, nome_arquivo)

        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        out = cv2.VideoWriter(caminho_arquivo, fourcc, self.fps,
                               (self.width, self.height))
        for f in frames:
            out.write(f)
        out.release()

        fim = time.time()
        latencia = fim - inicio
        duracao_video = len(frames) / self.fps if self.fps else 0
        perdidos = self.frames_perdidos()

        registrar_evento(timestamp_evento, self.camera_id, nome_arquivo,
                          len(frames), duracao_video, latencia, perdidos)

        print(f"[OK] [{self.camera_id}] Vídeo salvo: {caminho_arquivo}")
        print(f"     Frames: {len(frames)} | Duração: {duracao_video:.2f}s | "
              f"Latência de gravação: {latencia:.3f}s")


def monitor_sistema(cameras, parar_evento):
    """
    Thread única que monitora CPU/RAM do processo (compartilhado por
    todas as câmeras) e, a cada intervalo, registra também o FPS real
    e o tamanho do buffer de CADA câmera individualmente.
    """
    processo = psutil.Process(os.getpid())
    ultimo_contador = {cam.camera_id: 0 for cam in cameras}

    while not parar_evento.is_set():
        time.sleep(INTERVALO_AMOSTRAGEM_METRICAS)

        cpu = psutil.cpu_percent(interval=None)
        ram_percent = processo.memory_percent()
        ram_mb = processo.memory_info().rss / (1024 * 1024)

        for cam in cameras:
            atual = cam.frames_capturados()
            fps_real = (atual - ultimo_contador[cam.camera_id]) / INTERVALO_AMOSTRAGEM_METRICAS
            ultimo_contador[cam.camera_id] = atual

            registrar_metrica_sistema(cam.camera_id, cpu, ram_percent, ram_mb,
                                       fps_real, cam.tamanho_buffer())

            print(f"[METRICAS] [{cam.camera_id}] CPU: {cpu:.1f}% | "
                  f"RAM: {ram_mb:.1f}MB ({ram_percent:.1f}%) | "
                  f"FPS real: {fps_real:.1f} | Buffer: {cam.tamanho_buffer()}/{cam.max_frames}")


def main():
    print("Gravando... Pressione 's' para salvar os últimos 30s de TODAS as câmeras.")
    print("Pressione um número (1-9) para salvar apenas a câmera correspondente.")
    print("Pressione 'q' para sair.")
    print(f"[INFO] Vídeos serão salvos em: ./{PASTA_VIDEOS}/")
    print(f"[INFO] Métricas serão salvas em: ./{PASTA_METRICAS}/")

    cameras = [
        CameraWorker(cfg["id"], cfg["nome"], cfg["index"])
        for cfg in CAMERAS
    ]
    for cam in cameras:
        cam.start()

    parar_monitor = threading.Event()
    thread_monitor = threading.Thread(
        target=monitor_sistema, args=(cameras, parar_monitor), daemon=True
    )
    thread_monitor.start()

    try:
        while True:
            for cam in cameras:
                with cam.lock:
                    frame = cam.frame_atual
                if frame is not None:
                    cv2.imshow(f"{cam.nome} ({cam.camera_id})", frame)

            key = cv2.waitKey(1) & 0xFF

            if key == ord('q'):
                print("Saindo...")
                break

            elif key == ord('s'):
                print("Salvando todas as câmeras...")
                timestamp_evento = datetime.now().strftime("%Y%m%d_%H%M%S")
                for cam in cameras:
                    threading.Thread(
                        target=cam.salvar_video, args=(timestamp_evento,)
                    ).start()

            elif ord('1') <= key <= ord('9'):
                indice = key - ord('1')
                if indice < len(cameras):
                    cam = cameras[indice]
                    print(f"Salvando câmera '{cam.camera_id}'...")
                    timestamp_evento = datetime.now().strftime("%Y%m%d_%H%M%S")
                    threading.Thread(
                        target=cam.salvar_video, args=(timestamp_evento,)
                    ).start()

    finally:
        parar_monitor.set()
        for cam in cameras:
            cam.parar()
        for cam in cameras:
            cam.join(timeout=2)
        cv2.destroyAllWindows()
        print(f"\n[INFO] Execução encerrada. Confira os CSVs em ./{PASTA_METRICAS}/ "
              f"para os dados coletados.")


if __name__ == "__main__":
    main()