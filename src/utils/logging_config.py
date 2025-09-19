# src/bomia/utils/logging_config.py

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Importar o novo sistema de configuração
try:
    from bomia.config import config
except ImportError:
    print("CRÍTICO: Falha ao importar configurações de bomia.config.", file=sys.stderr)
    config = None

def setup_logging():
    """Configura o logging baseado no sistema de configuração."""
    
    # Obter nível de log e arquivo da configuração
    if config:
        log_level_str = config.get("logging.level", "INFO")
        log_file_path = config.path("logs") if config.get("logging.file") else None
    else:
        print("Aviso: Configuração não disponível. Usando configurações padrão de logging (INFO, Console).", file=sys.stderr)
        log_level_str = 'INFO'
        log_file_path = None

    # Validar nível de log
    log_level = getattr(logging, log_level_str, logging.INFO)
    if not isinstance(log_level, int):
        print(f"Aviso: Nível de log inválido '{log_level_str}'. Usando INFO como padrão.", file=sys.stderr)
        log_level = logging.INFO

    # Formatter padrão
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    # Obter logger raiz
    root_logger = logging.getLogger()

    # Limpar handlers existentes
    if root_logger.hasHandlers():
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
            handler.close()

    root_logger.setLevel(log_level)

    # Handler para Console (sempre adicionado)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(log_level)
    root_logger.addHandler(console_handler)

    # Handler para Arquivo (se configurado)
    if log_file_path:
        try:
            # Garantir que o diretório exista
            log_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # RotatingFileHandler para melhor gestão de logs
            max_bytes = 5 * 1024 * 1024  # 5 MB
            backup_count = 3
            file_handler = RotatingFileHandler(
                filename=log_file_path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setFormatter(log_formatter)
            file_handler.setLevel(log_level)
            root_logger.addHandler(file_handler)
            
            logging.info(f"Logging para arquivo configurado: Nível={log_level_str}, Arquivo={log_file_path}")
        except Exception as e:
            print(f"Aviso: Não foi possível configurar o handler de arquivo para {log_file_path}: {e}", file=sys.stderr)
            logging.error(f"Falha ao configurar handler de arquivo: {e}")
    else:
        logging.info(f"Logging para console configurado: Nível={log_level_str}. Logging para arquivo desativado.")