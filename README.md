# Sistema de Recuperação Temporal de Vídeo com Buffer Circular

Protótipo de captura contínua de vídeo com buffer circular (janela deslizante) e
acionamento por evento, desenvolvido como parte do TCC *"Um Estudo sobre
Recuperação Temporal de Vídeo em Ambientes Multicâmera Embarcados Baseado em
Buffer Circular e Acionamento por Evento"*.

O sistema mantém em memória apenas os últimos N segundos de vídeo capturado
pela câmera. Ao pressionar uma tecla, os frames armazenados até aquele momento
são salvos permanentemente em disco, evitando a necessidade de gravação
contínua e integral.

## Funcionalidades

- Captura contínua de vídeo via webcam
- Buffer circular (`deque`) mantendo janela dos últimos 30 segundos
- Salvamento sob demanda (tecla `s`) em arquivo `.avi` local
- Coleta de métricas de desempenho durante a execução:
  - Uso de CPU e RAM do processo
  - FPS real medido (vs. FPS configurado)
  - Frames perdidos estimados
  - Latência de gravação de cada evento salvo

## Pré-requisitos

- **Python 3.9 ou superior**
- Webcam (interna do notebook ou USB) reconhecida pelo sistema operacional

## Instalação

1. Clone o repositório:
   ```bash
   git clone <url-do-repositorio>
   cd <nome-da-pasta>
   ```

2. (Recomendado) Crie um ambiente virtual:
   ```bash
   python -m venv venv
   ```

   Ative o ambiente virtual:
   - Windows:
     ```bash
     venv\Scripts\activate
     ```
   - Linux/macOS:
     ```bash
     source venv/bin/activate
     ```

3. Instale as dependências:
   ```bash
   pip install opencv-python psutil
   ```

   Ou, se preferir usar um arquivo de dependências, crie um `requirements.txt`
   com o conteúdo abaixo e instale com `pip install -r requirements.txt`:
   ```
   opencv-python
   psutil
   ```

## Como executar

```bash
python main_com_metricas.py
```

Uma janela com a imagem da webcam será aberta. Controles:

| Tecla | Ação |
|---|---|
| `s` | Salva os últimos 30 segundos do buffer em um arquivo `.avi` |
| `q` | Encerra a aplicação |

## Estrutura de pastas gerada

Ao rodar, o script cria automaticamente:

```
.
├── gravacoes/          # vídeos .avi salvos ao pressionar 's'
└── metricas/
    ├── sistema_<timestamp>.csv   # CPU, RAM e FPS amostrados a cada 1s
    └── eventos_<timestamp>.csv   # dados de cada gravação (latência, frames, etc.)
```

## Configurações ajustáveis

No topo do arquivo `main_com_metricas.py`:

```python
BUFFER_SECONDS = 30      # duração da janela do buffer, em segundos
FPS = 30                 # FPS nominal usado para dimensionar o buffer e salvar o vídeo
FRAME_WIDTH = 640        # resolução de captura
FRAME_HEIGHT = 480
```

> **Atenção:** o FPS real da sua webcam pode ser menor que o configurado
> (verifique a coluna `fps_real` no CSV de sistema). Se houver divergência
> significativa, o vídeo salvo pode parecer acelerado, pois o buffer é
> dimensionado com base no FPS nominal, não no medido.

## Limitações conhecidas (versão atual)

- Suporta apenas **uma câmera** por vez (webcam local via `cv2.VideoCapture(0)`)
- Ainda não integrado ao Raspberry Pi (uso da câmera nativa via `picamera2`)
- Estimativa de frames perdidos é baseada em timing, não em contagem exata do driver
- Sem sincronização entre múltiplos dispositivos de captura

## Próximos passos

- Suporte a múltiplas câmeras simultâneas (arquitetura multicâmera)
- Migração da captura para Raspberry Pi com módulo de câmera nativo
- Buffer baseado em timestamp em vez de contagem fixa de frames

## Declaração de uso de IA

Ferramentas de Inteligência Artificial generativa foram utilizadas como apoio
auxiliar na elaboração deste projeto, incluindo revisão de código e
estruturação de documentação, sem substituir a autoria intelectual ou as
decisões técnicas dos autores.
