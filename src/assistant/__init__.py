"""WhatsApp assistant for farmers, backed by the comparar_rotaciones tool.

- tools.py:      the tools (plain Python functions), their JSON schemas, and the compact result the LLM sees
- prompts.py:    the Spanish system prompt
- agent.py:      the conversation loop with Claude (tool use), one history per phone number
- mcp_server.py: the same tools as an MCP server (Claude Desktop, other clients)
- whatsapp.py:   the Twilio WhatsApp webhook (FastAPI)
- simulate.py:   chat in the terminal, or replay scripted farmer conversations
"""
