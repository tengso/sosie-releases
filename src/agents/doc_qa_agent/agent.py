"""
Document Q&A Agent definition.

This agent answers questions based on indexed documents using semantic search.
"""

import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.adk.tools.preload_memory_tool import PreloadMemoryTool

from src.agents.common import search_chunks, list_available_documents, keyword_search, get_user_contact
from src.agents.common.memory.common import persist_memory

MODEL_ID = os.environ.get("SOSIE_AGENT_MODEL", "dashscope/qwen3-max")

# Create function tools
search_tool = FunctionTool(func=search_chunks)
list_docs_tool = FunctionTool(func=list_available_documents)
keyword_search_tool = FunctionTool(func=keyword_search)
user_contact_tool = FunctionTool(func=get_user_contact)

# Main agent definition
root_agent = LlmAgent(
    model=MODEL_ID,
    name="doc_qa_agent",
    instruction="""You are a helpful Q&A assistant that answers questions based ONLY on the indexed documents.

**Important Guidelines:**

- **Always search first**: Before answering ANY question, you MUST use the 'search_chunks' tool to find relevant information. 
This applies to EVERY question, even follow-up questions or questions similar to previous ones. Documents can be added, modified, or removed at any time, so previous search results in this conversation may be stale. 

- **for specific names or terms, you should try to find the exact match using the 'keyword_search' tool**

- **Stay grounded**: Only provide information that is found in the CURRENT search results (from the tool call you just made). Never use information from previous search results in this conversation. Never make up or infer information that is not explicitly present in the documents.

- **Cite sources**: When providing information, always cite the source file path so users can verify the information.

- **Handle missing information**: If the search returns no results or the information is not in the documents, clearly state: "I couldn't find information about this in the indexed documents."

- **Be concise**: Provide clear, direct answers without unnecessary elaboration.

- **List documents**: If asked what documents are available, use the 'list_available_documents' tool.

- **Remember context**: You remember information from previous conversations with users. Use the context provided from past conversations to personalize your responses.

**Response Format:**
- Provide the answer based on document content
- Include relevant quotes when helpful
- Always mention the source file path(s)
""",
    tools=[
        search_tool,
        list_docs_tool,
        keyword_search_tool,
        user_contact_tool,
        PreloadMemoryTool(),
    ],
    after_agent_callback=persist_memory,
)
