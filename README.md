# Bomia Annotator

Sistema standalone de anotação para o projeto Bomia Engine, especializado em detecção e classificação de objetos em streams de vídeo de segurança industrial.

## Visão Geral

O Bomia Annotator é uma ferramenta de anotação de imagens derivada do Bomia Engine, mantendo compatibilidade total com o formato de dados e lógica de anotação do sistema principal. Foi desenvolvido para permitir trabalho distribuído de anotação sem necessidade de acesso ao código fonte completo do Bomia Engine.

## Arquitetura

### Componentes Principais

- **Annotation Engine**: Motor de anotação baseado em OpenCV para criação e manipulação de bounding boxes
- **State Management**: Sistema de gerenciamento de estado para controle de navegação e edição
- **Storage Layer**: Camada de persistência em JSON com estrutura compatível com Bomia Engine
- **S3 Integration**: Cliente boto3 para sincronização de frames com buckets S3
- **Configuration System**: Sistema de configuração hierárquico baseado em YAML

### Estrutura de Diretórios

```
bomia-annotator/
├── configs/
│   ├── default.yaml         # Configurações base do sistema
│   ├── local.yaml           # Overrides locais (gitignored)
│   └── local.example.yaml   # Template de configuração
├── data/
│   └── {project_name}/
│       ├── raw-frames/      # Frames baixados do S3
│       ├── annotations.json # Arquivo de anotações
│       └── models/          # Modelos YOLO (opcional)
├── scripts/
│   ├── annotate.py          # Entry point principal
│   └── sync/
│       ├── s3_downloader.py # Download de frames do S3
│       └── s3_list_files.py # Listagem de arquivos no S3
├── src/
│   ├── annotator/           # Módulos de anotação
│   ├── config/              # Gerenciamento de configuração
│   ├── project_config/      # Configurações por projeto
│   └── utils/               # Utilitários
└── requirements.txt         # Dependências Python
```

## Projeto Portaria-Entrada

### Especificações Técnicas

O projeto `portaria-entrada` visa a detecção e classificação de veículos em área de controle de acesso, utilizando câmera fixa posicionada com visão frontal da cancela de entrada.

### Sistema de Categorização

#### Categoria Ativa

| ID | Nome | Descrição | Critérios de Aplicação |
|----|------|-----------|------------------------|
| 1 | `veiculo_na_portaria` | Veículo em posição de espera na regiao da portaria. | Veículo (carro, moto, caminhão) posicionado na área delimitada da portaria, aguardando liberação de acesso. |ss


### Formato de Dados

#### Estrutura JSON de Anotações

```json
{
  "timestamp.jpg": {
    "annotations": [
      {
        "bbox": [x1, y1, x2, y2],
        "category_id": "1",
        "category_name": "veiculo_na_portaria",
        "annotation_source": "human",
        "confidence": null,
        "subcategory_id": null,
        "subcategory_name": null
      }
    ],
    "original_path": "/absolute/path/to/image.jpg",
    "created_at_iso": "2024-01-19T10:00:00.000Z",
    "updated_at_iso": "2024-01-19T10:00:00.000Z"
  }
}
```

#### Especificações de Bounding Box

- **Formato**: `[x1, y1, x2, y2]` onde (x1,y1) = canto superior esquerdo, (x2,y2) = canto inferior direito
- **Sistema de coordenadas**: Pixels absolutos da imagem original
- **Validação**: Área mínima de 100px², sem sobreposição superior a 50% IoU

## Instalação

### Requisitos de Sistema

- Python 3.11+
- OpenCV 4.7.0+
- 4GB RAM mínimo
- 10GB espaço em disco para frames
- Conexão estável com S3 (mínimo 10Mbps)

### Setup do Ambiente

```bash
# Clone do repositório
git clone https://github.com/shudbr/bomia-annotator.git
cd bomia-annotator

# Criação do ambiente virtual
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# ou
venv\Scripts\activate     # Windows

# Instalação de dependências
pip install -r requirements.txt
```

### Configuração

#### 1. Configuração Base

Copie o template de configuração:

```bash
cp configs/local.example.yaml configs/local.yaml
```

#### 2. Configuração do Projeto

Edite `configs/local.yaml`:

```yaml
# Projeto ativo
active_project: "portaria-entrada"

# Credenciais AWS S3
s3:
  bucket: "bomia-frames"
  region: "us-east-1"
  endpoint: "s3.amazonaws.com"
  access_key: "${AWS_ACCESS_KEY_ID}"
  secret_key: "${AWS_SECRET_ACCESS_KEY}"

# Paths customizados (opcional)
paths:
  data_root: "data/{project.name}"
  raw_frames: "{paths.data_root}/raw-frames"
  annotations: "{paths.data_root}/annotations.json"
```

#### 3. Variáveis de Ambiente (Alternativa)

```bash
export BOMIA_PROJECT="portaria-entrada"
export AWS_ACCESS_KEY_ID="your-access-key"
export AWS_SECRET_ACCESS_KEY="your-secret-key"
```

## Sincronização com S3

### Download de Frames

#### Sintaxe Completa

```bash
python scripts/sync/s3_downloader.py [OPTIONS]
```

#### Opções Disponíveis

| Opção | Descrição | Default |
|-------|-----------|---------|
| `--project` | Nome do projeto | `portaria-entrada` |
| `--limit` | Número máximo de frames | Sem limite |
| `--date` | Data específica (YYYY-MM-DD) | Todos |
| `--start-date` | Data inicial do range | - |
| `--end-date` | Data final do range | - |
| `--prefix` | Prefixo S3 customizado | Auto-detectado |
| `--workers` | Threads paralelas | 10 |
| `--force` | Sobrescrever existentes | False |

#### Exemplos de Uso

```bash
# Download dos últimos 1000 frames
python scripts/sync/s3_downloader.py --limit 1000

# Download de data específica
python scripts/sync/s3_downloader.py --date 2024-01-19

# Download de intervalo
python scripts/sync/s3_downloader.py --start-date 2024-01-15 --end-date 2024-01-19

# Download com paralelismo aumentado
python scripts/sync/s3_downloader.py --limit 5000 --workers 20

# Forçar re-download
python scripts/sync/s3_downloader.py --date 2024-01-19 --force
```

### Listagem de Arquivos Disponíveis

```bash
# Listar arquivos no bucket
python scripts/sync/s3_list_files.py --project portaria-entrada

# Contar arquivos por data
python scripts/sync/s3_list_files.py --project portaria-entrada --count-by-date
```

## Utilização

### Execução do Anotador

```bash
python scripts/annotate.py [OPTIONS]
```

### Opções de Linha de Comando

| Opção | Descrição | Default |
|-------|-----------|---------|
| `--project` | Override do projeto ativo | Config file |
| `--model` | Caminho para modelo YOLO | Auto-detect |
| `--conf` | Threshold de confiança | 0.35 |
| `--category-filter` | Filtro de categoria | None |

### Controles de Interface

#### Navegação

| Tecla | Função | Descrição Técnica |
|-------|--------|-------------------|
| `A`/`←` | Frame anterior | Decrementa índice do frame |
| `D`/`→` | Próximo frame | Incrementa índice do frame |
| `W`/`↑` | Avanço rápido | Pula 10 frames (configurável) |
| `S`/`↓` | Retrocesso rápido | Retrocede 10 frames |
| `[` | Frame anotado anterior | Busca índice com annotations.length > 0 |
| `]` | Próximo frame anotado | Busca próximo índice anotado |
| `G` | Goto frame | Input direto de índice |

#### Manipulação de Bounding Boxes

| Tecla | Função | Comportamento |
|-------|--------|---------------|
| `Mouse LClick+Drag` | Criar bbox | Desenha retângulo com validação de área mínima |
| `TAB` | Selecionar próximo | Cicla entre bboxes no frame (índice++) |
| `Shift+TAB` | Selecionar anterior | Cicla reverso (índice--) |
| `1-9` | Atribuir categoria | Define category_id para bbox selecionado |
| `DELETE` | Remover selecionado | Remove bbox do array de annotations |
| `X` | Limpar frame | Remove todas annotations do frame atual |
| `R` | Repetir último | Clona último bbox com mesma categoria |

#### Funcionalidades Avançadas

| Tecla | Função | Descrição |
|-------|--------|-----------|
| `I` | Executar inferência | Roda modelo YOLO se disponível |
| `Space` | Confirmar inferência | Converte bbox temporário em permanente |
| `C` | Confirmar todas | Batch confirm de inferências |
| `ESC` | Cancelar temporários | Limpa bboxes não confirmados |
| `B` | Fixed bboxes | Cria bboxes pré-definidos do projeto |
| `K` | Toggle auto-skip | OFF→Frame→Annotated (ciclo) |
| `V` | Display mode | Alterna visualização de metadados |

#### Sistema

| Tecla | Função | Detalhes |
|-------|--------|----------|
| `H` | Help overlay | Toggle da sobreposição de ajuda |
| `T` | Statistics | Mostra estatísticas de anotação |
| `Q` (2x) | Quit | Salva e encerra (requer confirmação) |

### Modos de Operação

#### Auto-Skip

Sistema de navegação automática após criação de bbox:

- **Mode 0 (OFF)**: Permanece no frame atual
- **Mode 1 (Frame)**: Avança para próximo frame
- **Mode 2 (Annotated)**: Avança para próximo frame não anotado

Delay configurável em `annotation.auto_skip_delay_seconds` (default: 1.5s)

#### Display Modes

- **Mode 0**: Visualização limpa (apenas bboxes)
- **Mode 1**: Metadados básicos (categoria, fonte)
- **Mode 2**: Debug completo (coordenadas, IDs, timestamps)

## Integração com Modelos

### Configuração de Inferência

O sistema suporta modelos YOLO para assistência na anotação:

```bash
# Com modelo específico
python scripts/annotate.py --model data/portaria-entrada/models/best.pt --conf 0.5

# Auto-detecção de modelo do projeto
python scripts/annotate.py  # Busca em data/{project}/models/{project}/weights/best.pt
```

### Workflow de Inferência

1. Pressione `I` para executar inferência
2. Navegue entre detecções com `TAB`
3. Ajuste categorias com teclas numéricas
4. Confirme com `Space` ou `C` para todas

## Performance e Otimização

### Configurações de Performance

```yaml
# Em configs/local.yaml
annotation:
  window_width_percent: 0.8   # Reduzir para melhor performance
  window_height_percent: 0.8
  cache_size: 50              # Número de frames em cache

collection:
  jpeg_quality: 75            # Qualidade de compressão
```

### Paralelização do Download

```bash
# Aumentar workers para conexões rápidas
python scripts/sync/s3_downloader.py --workers 30 --limit 10000

# Reduzir para conexões instáveis
python scripts/sync/s3_downloader.py --workers 5 --limit 1000
```

## Troubleshooting

### Problemas Comuns

#### ImportError em módulos

```bash
# Verificar ativação do venv
which python  # Deve apontar para venv/bin/python

# Reinstalar dependências
pip install --upgrade -r requirements.txt
```

#### S3 Connection Timeout

```bash
# Verificar credenciais
aws s3 ls s3://bomia-frames/portaria-entrada/ --profile bomia

# Testar com endpoint direto
python scripts/sync/s3_list_files.py --debug
```

#### OpenCV Window Not Responding

```bash
# Verificar backend do OpenCV
python -c "import cv2; print(cv2.getBuildInformation())"

# Forçar backend específico
export OPENCV_VIDEOIO_PRIORITY_BACKEND=0
```

### Logs e Debug

```bash
# Ativar logs verbose
export BOMIA_LOG_LEVEL=DEBUG
python scripts/annotate.py

# Verificar logs
tail -f logs/portaria-entrada_logs.log
```

## Desenvolvimento

### Estrutura de Código

```
src/
├── annotator/
│   ├── annotator.py    # Classe principal UnifiedAnnotator
│   ├── state.py        # AnnotationState management
│   ├── store.py        # AnnotationStore (JSON persistence)
│   ├── renderer.py     # AnnotationRenderer (OpenCV drawing)
│   ├── key_handler.py  # Keyboard/mouse event handling
│   └── definitions.py  # Categories and subcategories
├── config/
│   ├── __init__.py     # Config singleton
│   └── manager.py      # ConfigManager class
└── utils/
    ├── logging_config.py
    └── s3_uploader.py
```

### Extensão do Sistema

Para adicionar novos projetos, edite `configs/default.yaml`:

```yaml
projects:
  novo-projeto:
    description: "Descrição do projeto"
    categories:
      '0': 'categoria_1'
      '1': 'categoria_2'
    visualization:
      colors:
        '0': [255, 0, 0]  # BGR format
        '1': [0, 255, 0]
```

## Licença e Contato

Propriedade intelectual da Shud Tecnologia Ltda.
Uso restrito a colaboradores autorizados do projeto Bomia.

**Repositório**: https://github.com/shudbr/bomia-annotator