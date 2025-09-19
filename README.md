# Bomia Annotator

Sistema standalone de anotações para o Bomia Engine. Ferramenta especializada para criar e gerenciar anotações em imagens, mantendo total compatibilidade com o formato JSON do Bomia Engine.

## Características

- Interface de anotação idêntica ao Bomia Engine
- Suporte completo para múltiplos projetos (sinterização, carbonização, portaria, etc.)
- Criação de bounding boxes com categorias
- Sistema de fixed bboxes para anotações padronizadas
- Suporte opcional para inferência com modelos YOLO
- Navegação eficiente entre frames
- Auto-skip após criação de bbox

## Instalação

### 1. Clone o repositório

```bash
git clone https://github.com/seu-usuario/bomia-annotator.git
cd bomia-annotator
```

### 2. Crie um ambiente virtual Python

```bash
python3 -m venv venv
source venv/bin/activate  # No Linux/Mac
# ou
venv\Scripts\activate  # No Windows
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

### 4. Configure o projeto

```bash
# Copie o arquivo de configuração exemplo
cp configs/local.example.yaml configs/local.yaml

# Edite o arquivo para definir seu projeto ativo
nano configs/local.yaml
```

## Configuração

### Definir projeto ativo

No arquivo `configs/local.yaml`, defina o projeto que você quer anotar:

```yaml
# Para portaria-entrada
active_project: "portaria-entrada"

# Para sinterizacao-1
active_project: "sinterizacao-1"

# Para carbonizacao-1
active_project: "carbonizacao-1"
```

### Estrutura de diretórios esperada

O sistema espera encontrar as imagens em:
```
data/
└── [nome-do-projeto]/
    ├── raw-frames/       # Imagens para anotar
    └── annotations.json  # Arquivo de anotações (será criado automaticamente)
```

## Uso

### Executar o anotador

```bash
python scripts/annotate.py
```

Ou especificar o projeto via linha de comando:

```bash
python scripts/annotate.py --project portaria-entrada
```

### Com modelo para inferência (opcional)

```bash
python scripts/annotate.py --model data/portaria-entrada/models/portaria-entrada/weights/best.pt
```

### Com filtro de categoria

```bash
python scripts/annotate.py --category-filter "veiculo_na_portaria"
```

## Atalhos de Teclado

### Navegação
- `A` / `←`: Frame anterior
- `D` / `→`: Próximo frame
- `W` / `↑`: Pular 10 frames para frente
- `S` / `↓`: Pular 10 frames para trás
- `[`: Frame anotado anterior
- `]`: Próximo frame anotado
- `G`: Ir para frame específico

### Anotações
- **Mouse**: Clique e arraste para criar bbox
- `0-9`: Define categoria para bbox selecionado
- `I/M/F`: Define subcategoria (início/meio/fim)
- `DELETE`: Remove bbox selecionado
- `TAB`: Seleciona próximo bbox
- `SHIFT+TAB`: Seleciona bbox anterior
- `X`: Remove todos os bboxes do frame atual

### Funcionalidades Especiais
- `B`: Cria fixed bboxes (para projetos configurados)
- `R`: Repete último bbox criado no frame atual
- `I` (maiúsculo): Executa inferência (requer modelo)
- `SPACE`: Confirma inferência selecionada
- `C`: Confirma todas as inferências
- `ESC`: Cancela inferências temporárias

### Modos de Auto-skip
- `K`: Alterna modo auto-skip (OFF/Frame/Anotado)

### Sistema
- `H`: Mostra/oculta ajuda
- `T`: Mostra/oculta estatísticas
- `V`: Alterna modo de visualização
- `Q` (2x): Sair do programa

## Categorias por Projeto

### Portaria Entrada
1. `veiculo_na_portaria`
2. `parcialmente_visivel`
3. `caminhao_presente`
4. `sem_caminhao`

### Sinterização-1
0. `operador`
1. `esteira_carga_sinter`
2. `panela_cura_ativa`
3. `panela_virando`
4. `estado_indefinido`
5. `panela_sem_material`

### Carbonização-1
0. `revisar`
1. `com_fumaca`
2. `sem_fumaca`
3. `operador`
4. `trator`
5. `grua`
6. `caminhao_toras`
7. `veiculo_outro`
8. `forno_aberto`
9. `fumaca_secagem`

## Formato de Saída

As anotações são salvas em formato JSON compatível com o Bomia Engine:

```json
{
  "1234567890.jpg": {
    "annotations": [
      {
        "bbox": [x1, y1, x2, y2],
        "category_id": "1",
        "category_name": "veiculo_na_portaria",
        "annotation_source": "human"
      }
    ],
    "original_path": "/path/to/image.jpg",
    "created_at_iso": "2024-01-19T10:30:00",
    "updated_at_iso": "2024-01-19T10:35:00"
  }
}
```

## Requisitos

- Python 3.11+
- OpenCV
- NumPy
- PyYAML
- Ultralytics (opcional, para inferência)
- PyTorch (opcional, para inferência)

## Suporte

Para reportar problemas ou sugestões, abra uma issue no repositório.

## Licença

Propriedade da Shud. Uso autorizado apenas para anotadores oficiais do projeto Bomia.