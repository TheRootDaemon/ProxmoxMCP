"""
Main server implementation for Proxmox MCP.

This module implements the core MCP server for Proxmox integration, providing:
- Configuration loading and validation
- Logging setup
- Proxmox API connection management
- MCP tool registration and routing
- Signal handling for graceful shutdown

The server exposes a set of tools for managing Proxmox resources including:
- Node management
- VM operations
- Storage management
- Cluster status monitoring
"""

import os
import signal
import sys
from typing import Annotated, List, Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent
from pydantic import Field

from .config.loader import load_config
from .core.logging import setup_logging
from .core.proxmox import ProxmoxManager
from .tools.ai_diagnostics import AIProxmoxDiagnostics
from .tools.cluster import ClusterTools
from .tools.container import ContainerTools
from .tools.definitions import (
    ANALYZE_CLUSTER_HEALTH_DESC,
    ANALYZE_SECURITY_POSTURE_DESC,
    DIAGNOSE_VM_ISSUES_DESC,
    EXECUTE_VM_COMMAND_DESC,
    GET_CLUSTER_STATUS_DESC,
    GET_CONTAINERS_DESC,
    GET_NODE_STATUS_DESC,
    GET_NODES_DESC,
    GET_STORAGE_DESC,
    GET_VMS_DESC,
    SUGGEST_RESOURCE_OPTIMIZATION_DESC,
)
from .tools.node import NodeTools
from .tools.storage import StorageTools
from .tools.vm import VMTools


class ProxmoxMCPServer:
    """Main server class for Proxmox MCP."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize the server.

        Args:
            config_path: Path to configuration file
        """
        self.config = load_config(config_path)
        self.logger = setup_logging(self.config.logging)

        # Initialize core components
        self.proxmox_manager = ProxmoxManager(self.config.proxmox, self.config.auth)
        self.proxmox = self.proxmox_manager.get_api()

        # Initialize tools
        self.node_tools = NodeTools(self.proxmox)
        self.vm_tools = VMTools(self.proxmox)
        self.container_tools = ContainerTools(self.proxmox)
        self.storage_tools = StorageTools(self.proxmox)
        self.cluster_tools = ClusterTools(self.proxmox)
        self.ai_diagnostics = AIProxmoxDiagnostics(self.proxmox)

        # Initialize MCP server
        self.mcp = FastMCP("ProxmoxMCP")
        self._setup_tools()

    def _setup_tools(self) -> None:
        """Register MCP tools with the server.

        Initializes and registers all available tools with the MCP server:
        - Node management tools (list nodes, get status)
        - VM operation tools (list VMs, execute commands)
        - Storage management tools (list storage)
        - Cluster tools (get cluster status)

        Each tool is registered with appropriate descriptions and parameter
        validation using Pydantic models.
        """

        # Node tools
        @self.mcp.tool(description=GET_NODES_DESC)
        def get_nodes() -> List[TextContent]:
            return self.node_tools.get_nodes()

        @self.mcp.tool(description=GET_NODE_STATUS_DESC)
        def get_node_status(
            node: Annotated[
                str,
                Field(description="Name/ID of node to query (e.g. 'pve1', 'proxmox-node2')"),
            ],
        ) -> List[TextContent]:
            return self.node_tools.get_node_status(node)

        # VM tools
        @self.mcp.tool(description=GET_VMS_DESC)
        def get_vms() -> List[TextContent]:
            return self.vm_tools.get_vms()

        # Container tools
        @self.mcp.tool(description=GET_CONTAINERS_DESC)
        def get_containers() -> List[TextContent]:
            return self.container_tools.get_containers()

        @self.mcp.tool(description=EXECUTE_VM_COMMAND_DESC)
        async def execute_vm_command(
            node: Annotated[
                str, Field(description="Host node name (e.g. 'pve1', 'proxmox-node2')")
            ],
            vmid: Annotated[str, Field(description="VM ID number (e.g. '100', '101')")],
            command: Annotated[
                str,
                Field(
                    description="Shell command to run (e.g. 'uname -a', 'systemctl status nginx')"
                ),
            ],
        ) -> List[TextContent]:
            return await self.vm_tools.execute_command(node, vmid, command)

        # Storage tools
        @self.mcp.tool(description=GET_STORAGE_DESC)
        def get_storage() -> List[TextContent]:
            return self.storage_tools.get_storage()

        # Cluster tools
        @self.mcp.tool(description=GET_CLUSTER_STATUS_DESC)
        def get_cluster_status() -> List[TextContent]:
            return self.cluster_tools.get_cluster_status()

        # AI Diagnostic tools
        @self.mcp.tool(description=ANALYZE_CLUSTER_HEALTH_DESC)
        async def analyze_cluster_health() -> List[TextContent]:
            return await self.ai_diagnostics.analyze_cluster_health()

        @self.mcp.tool(description=DIAGNOSE_VM_ISSUES_DESC)
        async def diagnose_vm_issues(
            node: Annotated[
                str,
                Field(
                    description="Proxmox node name hosting the VM (e.g. 'pve1', 'proxmox-node2')"
                ),
            ],
            vmid: Annotated[
                str,
                Field(description="Virtual machine ID to diagnose (e.g. '100', '101')"),
            ],
        ) -> List[TextContent]:
            return await self.ai_diagnostics.diagnose_vm_issues(node, vmid)

        @self.mcp.tool(description=SUGGEST_RESOURCE_OPTIMIZATION_DESC)
        async def suggest_resource_optimization() -> List[TextContent]:
            return await self.ai_diagnostics.suggest_resource_optimization()

        @self.mcp.tool(description=ANALYZE_SECURITY_POSTURE_DESC)
        async def analyze_security_posture() -> List[TextContent]:
            return await self.ai_diagnostics.analyze_security_posture()

    def start(self) -> None:
        """Start the MCP server.

        Initializes the server with:
        - Signal handlers for graceful shutdown (SIGINT, SIGTERM)
        - Async runtime for handling concurrent requests
        - Error handling and logging

        The server runs until terminated by a signal or fatal error.
        """
        import anyio

        def signal_handler(signum: int, frame: object) -> None:
            self.logger.info("Received signal to shutdown...")
            sys.exit(0)

        # Set up signal handlers
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        try:
            self.logger.info("Starting MCP server...")
            anyio.run(self.mcp.run_stdio_async)
        except Exception as e:
            self.logger.error(f"Server error: {e}")
            sys.exit(1)


if __name__ == "__main__":
    config_path = os.getenv("PROXMOX_MCP_CONFIG")
    if not config_path:
        print("PROXMOX_MCP_CONFIG environment variable must be set")
        sys.exit(1)

    try:
        server = ProxmoxMCPServer(config_path)
        server.start()
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
