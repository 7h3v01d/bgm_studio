@echo off
cd /d "%~dp0"
rem MCP server over HTTP at http://127.0.0.1:8766/mcp  (for stdio, point your MCP client at: .venv\Scripts\python.exe -m bgmstudio.mcp_server)
".venv\Scripts\python.exe" -m bgmstudio.mcp_server --http --port 8766
pause
