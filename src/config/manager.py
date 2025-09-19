# src/bomia/config_manager.py

import os
import re
import yaml
import logging
from pathlib import Path
from typing import Any, Dict, Optional, List, Union, Tuple

logger = logging.getLogger(__name__)

class ConfigManager:
    """
    Gerenciador central de configurações do Bomia Engine.
    Carrega configurações de arquivos YAML e fornece acesso estruturado.
    """
    
    def __init__(self, project_name: Optional[str] = None):
        self.config_data: Dict[str, Any] = {}
        self.project_name = project_name
        self.root_dir = Path(__file__).parent.parent.parent.resolve()
        
        # Carregar a configuração base
        self._load_config()
        
        # Interpolar variáveis nos paths
        self._interpolate_paths()
        
    def _load_config(self) -> None:
        """Carrega a configuração base e local."""
        default_config_path = self.root_dir / "configs" / "default.yaml"
        
        # Carregar configuração padrão
        if default_config_path.exists():
            with open(default_config_path, 'r') as f:
                self.config_data = yaml.safe_load(f)
            logger.info(f"Configuração base carregada: {default_config_path}")
        else:
            logger.warning(f"Arquivo de configuração base não encontrado: {default_config_path}")
            self.config_data = {}
        
        # Carregar configuração local (overrides)
        local_config_path = self.root_dir / "configs" / "local.yaml"
        if local_config_path.exists():
            try:
                with open(local_config_path, 'r') as f:
                    local_config = yaml.safe_load(f)
                    if local_config:
                        self._merge_configs(self.config_data, local_config)
                        logger.info(f"Configuração local aplicada de: {local_config_path}")
            except Exception as e:
                logger.warning(f"Erro ao carregar configuração local: {e}")
        
        # Apply active project configuration
        self._apply_active_project()
        
        # Verificar se há projeto especificado via CLI ou env
        cli_project = self.project_name or os.environ.get("BOMIA_PROJECT")
        if cli_project:
            # Override the active project and re-apply
            self.config_data["active_project"] = cli_project
            self._apply_active_project()
            logger.info(f"Usando projeto especificado externamente: {cli_project}")
        
        # Extrair o nome do projeto (já mesclado ou definido acima)
        self.project_name = self.config_data.get("project", {}).get("name", "default")
    
    def _merge_configs(self, base: Dict, override: Dict) -> None:
        """Mescla recursivamente as configurações de override em base."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._merge_configs(base[key], value)
            else:
                base[key] = value
    
    def _apply_active_project(self) -> None:
        """Apply the active project configuration."""
        # Use project_name from constructor if provided, otherwise use active_project from config
        active_project = self.project_name or self.config_data.get("active_project")
        projects = self.config_data.get("projects", {})
        
        if not active_project:
            # No active project specified, use default behavior
            return
        
        if active_project not in projects:
            logger.warning(f"Active project '{active_project}' not found in projects")
            return
        
        project_config = projects[active_project]
        logger.info(f"Using active project: {active_project}")
        
        # Update the project section for backward compatibility
        self.config_data["project"] = {
            "name": active_project,
            "description": project_config.get("description", f"Project {active_project}")
        }
        
        # Merge project-specific settings into main config
        for key, value in project_config.items():
            if key == "description":
                continue  # Already handled above
            
            # Merge project-specific configurations
            if key in self.config_data:
                if isinstance(self.config_data[key], dict) and isinstance(value, dict):
                    self._merge_configs(self.config_data[key], value)
                else:
                    self.config_data[key] = value
            else:
                self.config_data[key] = value
    
    def _interpolate_paths(self) -> None:
        """Interpola variáveis nos paths, ex: {project.name} -> 'sinterizacao-1'"""
        if "paths" not in self.config_data:
            return
        
        paths = self.config_data["paths"]
        processed = set()
        max_iterations = 10  # Prevent infinite loops
        iteration = 0
        
        # Continue interpolando até que todas as variáveis sejam resolvidas
        while iteration < max_iterations:
            iteration += 1
            unresolved = False
            changes_made = False
            
            for key, value in paths.items():
                if key in processed or not isinstance(value, str):
                    continue
                
                # Procurar variáveis no formato {section.key}
                var_pattern = r'\{([a-zA-Z0-9_.]+)\}'
                matches = re.findall(var_pattern, value)
                
                if not matches:
                    processed.add(key)
                    continue
                
                # Tentar resolver cada variável
                new_value = value
                all_resolved = True
                
                for match in matches:
                    parts = match.split('.')
                    config_value = self.config_data
                    
                    try:
                        for part in parts:
                            config_value = config_value[part]
                        
                        if isinstance(config_value, str):
                            new_value = new_value.replace(f"{{{match}}}", config_value)
                            changes_made = True
                        else:
                            all_resolved = False
                    except (KeyError, TypeError):
                        # Skip unresolvable variables (like {project.name} when no project is set)
                        all_resolved = False
                
                if all_resolved:
                    paths[key] = new_value
                    processed.add(key)
                elif new_value != value:
                    # Partial resolution - save progress
                    paths[key] = new_value
                else:
                    unresolved = True
            
            # Se não houver mais variáveis não resolvidas ou mudanças, pare
            if not unresolved or not changes_made or len(processed) == len(paths):
                break
        
        if iteration >= max_iterations:
            logger.warning(f"Path interpolation reached maximum iterations ({max_iterations}). Some paths may not be fully resolved.")
    
    def get(self, path: str, default: Any = None) -> Any:
        """
        Acessa um valor de configuração usando notação de pontos.
        Exemplo: config.get('project.name')
        """
        parts = path.split('.')
        value = self.config_data
        
        try:
            for part in parts:
                value = value[part]
            return value
        except (KeyError, TypeError):
            return default
    
    def path(self, config_path: str) -> Path:
        """
        Retorna um objeto Path a partir de uma configuração de caminho.
        Garante que o diretório pai exista.
        """
        path_str = self.get(f"paths.{config_path}")
        if not path_str:
            raise ValueError(f"Caminho '{config_path}' não encontrado na configuração")
        
        path = Path(path_str)
        if not path.is_absolute():
            path = self.root_dir / path
        
        # Criar o diretório pai se for um arquivo
        if '.' in path.name:  # Heurística simples para identificar arquivos
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
            
        return path
    
    def __getitem__(self, key: str) -> Any:
        """Permite acessar configurações usando notação de colchetes: config['project.name']"""
        return self.get(key)
    
    @property
    def project(self) -> str:
        """Atalho para o nome do projeto atual"""
        return self.project_name
    
    def get_str(self, path: str, default: str = "") -> str:
        """Obtém uma string da configuração"""
        value = self.get(path, default)
        return str(value)
    
    def get_int(self, path: str, default: int = 0) -> int:
        """Obtém um inteiro da configuração"""
        value = self.get(path, default)
        return int(value)
    
    def get_float(self, path: str, default: float = 0.0) -> float:
        """Obtém um float da configuração"""
        value = self.get(path, default)
        return float(value)
    
    def get_bool(self, path: str, default: bool = False) -> bool:
        """Obtém um boolean da configuração"""
        value = self.get(path, default)
        return bool(value)
    
    def get_list(self, path: str, default: Optional[List] = None) -> List:
        """Obtém uma lista da configuração"""
        value = self.get(path, default or [])
        return list(value) if hasattr(value, '__iter__') and not isinstance(value, (str, dict)) else [value]
    
    def get_tuple(self, path: str, default: Optional[Tuple] = None) -> Tuple:
        """Obtém uma tupla da configuração"""
        value = self.get(path, default or ())
        return tuple(value) if hasattr(value, '__iter__') and not isinstance(value, (str, dict)) else (value,)
    
    def get_dict(self, path: str, default: Optional[Dict] = None) -> Dict:
        """Obtém um dicionário da configuração"""
        value = self.get(path, default or {})
        if isinstance(value, dict):
            return value
        logger.warning(f"Valor em '{path}' não é um dicionário. Retornando default: {default}")
        return default or {}
        
    def get_rtsp_url(self) -> str:
        """
        Constrói e retorna a URL RTSP completa.
        Suporta dois formatos:
        1. URL RTSP direta: camera.rtsp_url
        2. Componentes individuais: username, password, ip, port, rtsp_stream_path
        """
        # Primeiro tenta usar URL RTSP direta
        rtsp_url = self.get("camera.rtsp_url")
        if rtsp_url:
            logger.info(f"Usando URL RTSP direta: {rtsp_url}")
            return rtsp_url
        
        # Caso contrário, constrói a partir dos componentes individuais
        username = self.get("camera.username")
        password = self.get("camera.password")
        ip = self.get("camera.ip")
        port = self.get("camera.port")
        path = self.get("camera.rtsp_stream_path")
        
        # Validar se todos os componentes necessários estão presentes
        if not all([username, password, ip, port, path]):
            missing = [key for key, val in {
                "username": username, "password": password, "ip": ip, 
                "port": port, "rtsp_stream_path": path
            }.items() if not val]
            raise ValueError(f"Campos obrigatórios da câmera faltando: {missing}. "
                           f"Configure camera.rtsp_url OU todos os campos individuais (username, password, ip, port, rtsp_stream_path)")
        
        constructed_url = f"rtsp://{username}:{password}@{ip}:{port}{path}"
        logger.info(f"URL RTSP construída a partir de componentes individuais: rtsp://***:***@{ip}:{port}{path}")
        return constructed_url
    
    def get_camera_groups(self) -> Dict[str, Any]:
        """
        Retorna a configuração de grupos de câmeras para multi-camera.
        """
        camera_groups = self.get_dict("camera_groups", {})
        if not camera_groups:
            logger.warning("Nenhum grupo de câmeras configurado em 'camera_groups'")
        return camera_groups
    
    def build_rtsp_url(self, camera_group: Dict[str, Any], channel: int) -> str:
        """
        Constrói URL RTSP a partir de um grupo de câmeras e canal.
        
        Args:
            camera_group: Dicionário com configuração do grupo de câmeras
            channel: Número do canal da câmera
            
        Returns:
            URL RTSP completa
        """
        rtsp_pattern = camera_group.get("rtsp_pattern", "")
        if not rtsp_pattern:
            raise ValueError("Campo 'rtsp_pattern' não encontrado no grupo de câmeras")
        
        # Substituir variáveis no padrão
        rtsp_url = rtsp_pattern.format(
            username=camera_group.get("username", ""),
            password=camera_group.get("password", ""),
            ip=camera_group.get("ip", ""),
            port=camera_group.get("port", ""),
            channel=channel
        )
        
        return rtsp_url