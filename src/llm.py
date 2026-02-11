"""
LLM Wrapper - Unified interface for Groq (cloud) and Ollama (local)

Groq free tier: 30 requests/min, llama-3.1-8b-instant
Falls back to local Ollama if GROQ_API_KEY not set
"""

import os
import asyncio
from typing import Optional
from loguru import logger

# Try importing groq
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False
    logger.debug("Groq not installed, will use Ollama only")

# Try importing ollama
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    logger.debug("Ollama not installed")


class LLM:
    """Unified LLM interface - Ollama (local, no rate limits) preferred, Groq fallback."""

    def __init__(self):
        self.groq_client: Optional[Groq] = None
        self.groq_model = "llama-3.1-8b-instant"  # Free tier model
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
        self.use_ollama = False

        # Prefer Ollama (no rate limits!)
        if OLLAMA_AVAILABLE:
            self.use_ollama = True
            logger.info(f"LLM: Using Ollama ({self.ollama_model}) - no rate limits!")
        # Fall back to Groq if Ollama not available
        elif GROQ_AVAILABLE:
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key:
                self.groq_client = Groq(api_key=groq_key)
                logger.info(f"LLM: Using Groq ({self.groq_model})")
            else:
                raise RuntimeError("GROQ_API_KEY not set and Ollama not available!")
        else:
            raise RuntimeError("No LLM available! Install ollama or groq package.")

    async def chat(self, prompt: str, json_mode: bool = False) -> str:
        """
        Send a chat message and get response.

        Args:
            prompt: The user prompt
            json_mode: If True, request JSON output format

        Returns:
            The assistant's response text
        """
        # Prefer Ollama (no rate limits)
        if self.use_ollama:
            return await self._ollama_chat(prompt, json_mode)
        elif self.groq_client:
            return await self._groq_chat(prompt, json_mode)
        else:
            return await self._ollama_chat(prompt, json_mode)

    async def _groq_chat(self, prompt: str, json_mode: bool) -> str:
        """Call Groq API."""
        try:
            kwargs = {
                "model": self.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 4096,
            }

            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            # Run in thread to not block
            response = await asyncio.to_thread(
                self.groq_client.chat.completions.create,
                **kwargs
            )

            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Groq API error: {e}")
            # Fallback to Ollama if available
            if OLLAMA_AVAILABLE:
                logger.info("Falling back to Ollama...")
                return await self._ollama_chat(prompt, json_mode)
            raise

    async def _ollama_chat(self, prompt: str, json_mode: bool) -> str:
        """Call local Ollama."""
        try:
            kwargs = {
                "model": self.ollama_model,
                "messages": [{"role": "user", "content": prompt}],
            }

            if json_mode:
                kwargs["format"] = "json"

            response = await asyncio.to_thread(
                ollama.chat,
                **kwargs
            )

            return response["message"]["content"]

        except Exception as e:
            logger.error(f"Ollama error: {e}")
            raise


# Singleton instance
llm = LLM()
