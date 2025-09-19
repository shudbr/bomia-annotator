# src/bomia/config.py
import os
import logging
import argparse
from typing import Optional

# Importar o ConfigManager
from .manager import ConfigManager

logger = logging.getLogger(__name__)

# Variável global para armazenar a instância configurada
_config_instance: Optional[ConfigManager] = None

def get_active_project() -> str:
    """
    Determina o projeto ativo com base nos argumentos CLI ou variáveis de ambiente.
    """
    # Verificar argumento CLI
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--project', type=str, help='Nome do projeto')
    args, _ = parser.parse_known_args()
    
    # Prioridade: CLI > ENV > None (usa padrão)
    return args.project or os.environ.get("BOMIA_PROJECT")

def get_config() -> ConfigManager:
    """
    Retorna a instância do ConfigManager, criando-a se necessário.
    """
    global _config_instance
    
    if _config_instance is None:
        project = get_active_project()
        try:
            _config_instance = ConfigManager(project_name=project)
            logger.info(f"Configuração carregada para o projeto: {_config_instance.project}")
        except Exception as e:
            logger.critical(f"Erro ao inicializar configurações: {e}", exc_info=True)
            raise
    
    return _config_instance

# Instância global do ConfigManager para uso em todo o código
config = get_config()