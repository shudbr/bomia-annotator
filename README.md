# Bomia Annotator

Sistema de anotação de imagens para o projeto Bomia Engine.

## Projeto Portaria-Entrada

Sistema para anotar frames da câmera de entrada da portaria. O objetivo é identificar e marcar veículos na área de entrada.

### Categorias de Anotação

**O que você deve marcar em cada frame:**

| Número | Nome | Quando usar |
|--------|------|-------------|
| 1 | veiculo_na_portaria | Quando tem um veículo parado na cancela esperando para entrar |
| 2 | parcialmente_visivel | Quando a placa do veículo está cortada ou não dá para ver completa |
| 3 | caminhao_presente | Quando tem um caminhão no frame mas ele não está na cancela |
| 4 | sem_caminhao | Quando não tem nenhum caminhão no frame |

**Importante:**
- Se o caminhão está na cancela, use categoria 1, não a 3
- Cada veículo deve ter seu próprio retângulo
- O retângulo deve cobrir o veículo inteiro que está visível

## Instalação Passo a Passo

### Passo 1: Baixar o programa

Abra o terminal e digite:

```bash
git clone https://github.com/shudbr/bomia-annotator.git
cd bomia-annotator
```

### Passo 2: Preparar o Python

Digite um comando por vez:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Nota:** No Windows, o segundo comando é diferente:
```bash
venv\Scripts\activate
```

### Passo 3: Configurar o sistema

Copie o arquivo de configuração:

```bash
cp configs/local.example.yaml configs/local.yaml
```

Abra o arquivo `configs/local.yaml` em um editor de texto e adicione:

```yaml
active_project: "portaria-entrada"

s3:
  access_key: "PEDIR_PARA_EQUIPE"
  secret_key: "PEDIR_PARA_EQUIPE"
```

**Importante:** Peça as credenciais (access_key e secret_key) para a equipe de desenvolvimento.

### Passo 4: Baixar as imagens para anotar

Para baixar 1000 imagens recentes:
```bash
python scripts/sync/s3_downloader.py --project portaria-entrada --limit 1000
```

Para baixar imagens de um dia específico:
```bash
python scripts/sync/s3_downloader.py --project portaria-entrada --date 2024-01-19
```

As imagens serão salvas em: `data/portaria-entrada/raw-frames/`

### Passo 5: Começar a anotar

```bash
python scripts/annotate.py
```

## Como Usar o Programa

### Criar um retângulo (bounding box)

1. Clique e segure o botão esquerdo do mouse
2. Arraste para fazer um retângulo ao redor do veículo
3. Solte o botão do mouse
4. Pressione o número da categoria (1, 2, 3 ou 4)

### Teclas para navegar

| Tecla | O que faz |
|-------|-----------|
| A ou ← | Volta uma imagem |
| D ou → | Próxima imagem |
| W | Pula 10 imagens para frente |
| S | Volta 10 imagens |
| [ | Vai para imagem anterior que já tem anotação |
| ] | Vai para próxima imagem que já tem anotação |
| G | Digite um número para ir direto para aquela imagem |

### Teclas para editar

| Tecla | O que faz |
|-------|-----------|
| TAB | Seleciona o próximo retângulo na imagem |
| DELETE | Apaga o retângulo selecionado |
| X | Apaga todos os retângulos da imagem atual |
| R | Copia o último retângulo que você fez |
| 1-4 | Define a categoria do retângulo selecionado |

### Outras teclas úteis

| Tecla | O que faz |
|-------|-----------|
| K | Liga/desliga o pulo automático (depois de criar um retângulo, pula para próxima imagem) |
| H | Mostra ou esconde a ajuda na tela |
| T | Mostra quantas imagens você já anotou |
| Q | Pressione 2 vezes seguidas para sair do programa (salva automaticamente) |

## Rotina Diária de Trabalho

### Manhã - Preparar o trabalho

1. Abra o terminal
2. Entre na pasta do projeto:
   ```bash
   cd bomia-annotator
   ```

3. Ative o ambiente Python:
   ```bash
   source venv/bin/activate
   ```

4. Baixe novas imagens:
   ```bash
   python scripts/sync/s3_downloader.py --project portaria-entrada --limit 500
   ```

5. Comece a anotar:
   ```bash
   python scripts/annotate.py
   ```

### Durante o trabalho

1. Use a tecla K para ativar o pulo automático (mais rápido)
2. Pressione T de vez em quando para ver seu progresso
3. O programa salva automaticamente suas anotações

### Fim do dia

1. Pressione Q duas vezes para sair
2. Suas anotações estão salvas em: `data/portaria-entrada/annotations.json`

## Resolução de Problemas

### "No images found" - Não encontrou imagens

Isso significa que não tem imagens na pasta. Solução:

```bash
python scripts/sync/s3_downloader.py --project portaria-entrada --limit 100
```

### "Access Denied" - Acesso negado ao baixar imagens

As credenciais do S3 estão erradas. Solução:
1. Abra o arquivo `configs/local.yaml`
2. Verifique se colocou a access_key e secret_key corretas
3. Peça novas credenciais se necessário

### O programa não abre

Verifique se ativou o ambiente Python:
```bash
source venv/bin/activate
```

Você deve ver `(venv)` no início da linha do terminal.

### As teclas não funcionam

Certifique-se que a janela da imagem está selecionada (clique nela).

## Informações Técnicas

### Onde ficam os arquivos

```
bomia-annotator/
├── configs/
│   └── local.yaml           # Suas configurações
├── data/
│   └── portaria-entrada/
│       ├── raw-frames/      # Imagens baixadas
│       └── annotations.json # Suas anotações
└── scripts/
    └── annotate.py          # Programa principal
```

### Formato das anotações

As anotações são salvas em formato JSON. Cada imagem tem uma lista de retângulos com:
- Coordenadas do retângulo (x1, y1, x2, y2)
- Categoria (1, 2, 3 ou 4)
- Nome da categoria
- Quem fez (human = pessoa, inference = computador)

## Contato

- Problemas com o programa: Reportar no GitHub
- Dúvidas sobre as categorias: Perguntar para o supervisor
- Credenciais do S3: Pedir para a equipe de TI