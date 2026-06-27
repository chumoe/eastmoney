from abc import ABC, abstractmethod
import os
import sys
import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from google import genai
from openai import OpenAI

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config.settings import (
    GEMINI_API_KEY, GEMINI_MODEL, GEMINI_API_ENDPOINT,
    LLM_PROVIDER,
    OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL
)


@dataclass
class ToolCall:
    """Represents a tool call request from the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ChatResponse:
    """Response from chat_with_tools method."""
    content: Optional[str]
    tool_calls: List[ToolCall]
    finish_reason: str  # "stop" or "tool_calls"
    raw_response: Any = None
    reasoning_content: Optional[str] = None  # For thinking mode models


class BaseLLMClient(ABC):
    @abstractmethod
    def generate_content(self, prompt: str) -> str:
        pass

    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto"
    ) -> ChatResponse:
        """
        Chat with function calling support.

        Args:
            messages: Conversation messages in OpenAI format
            tools: List of tool definitions
            tool_choice: "auto", "none", or "required"

        Returns:
            ChatResponse with content and/or tool_calls
        """
        raise NotImplementedError("Subclass must implement chat_with_tools")

class GoogleGeminiClient(BaseLLMClient):
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        api_endpoint = os.getenv("GEMINI_API_ENDPOINT")
        model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-exp")

        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in environment variables.")

        client_kwargs = {"api_key": api_key}

        # Configure custom endpoint if provided
        if api_endpoint:
            client_kwargs["http_options"] = {"base_url": api_endpoint, "api_version": "v1alpha"}

        self.client = genai.Client(**client_kwargs)
        self.model_name = model

    def generate_content(self, prompt: str) -> str:
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            if response.text:
                return response.text
            return "Error: No text returned from model."
        except Exception as e:
            print(f"Error generating content with Gemini: {e}")
            return f"Error: Could not generate analysis. Details: {str(e)}"

    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto"
    ) -> ChatResponse:
        """
        Chat with function calling support for Gemini.

        Note: Gemini has different function calling API. This implementation
        converts to/from OpenAI format for consistency.
        """
        try:
            from google.genai import types

            # Convert messages to Gemini format
            contents = []
            system_instruction = None

            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")

                if role == "system":
                    system_instruction = content
                elif role == "user":
                    contents.append(types.Content(
                        role="user",
                        parts=[types.Part(text=content)]
                    ))
                elif role == "assistant":
                    parts = []
                    # Handle tool calls in assistant message
                    tool_calls = msg.get("tool_calls", [])
                    if tool_calls:
                        for tc in tool_calls:
                            func = tc.get("function", {})
                            try:
                                args = json.loads(func.get("arguments", "{}")) if func.get("arguments") else {}
                            except json.JSONDecodeError:
                                args = {}
                            parts.append(types.Part(
                                function_call=types.FunctionCall(
                                    name=func.get("name", ""),
                                    args=args
                                )
                            ))
                    # Add text content if present
                    if content:
                        parts.append(types.Part(text=content))
                    contents.append(types.Content(role="model", parts=parts))
                elif role == "tool":
                    # Tool result message
                    # Gemini's FunctionResponse needs the function name
                    tool_name = msg.get("name", "tool_response")
                    try:
                        response_data = json.loads(content) if content else {}
                    except json.JSONDecodeError:
                        response_data = {"result": content}
                    tool_response = types.Part(
                        function_response=types.FunctionResponse(
                            name=tool_name,
                            response=response_data
                        )
                    )
                    contents.append(types.Content(role="user", parts=[tool_response]))

            # Convert tools to Gemini format
            gemini_tools = None
            if tools:
                function_declarations = []
                for tool in tools:
                    if tool.get("type") == "function":
                        func = tool.get("function", {})
                        function_declarations.append(types.FunctionDeclaration(
                            name=func.get("name", ""),
                            description=func.get("description", ""),
                            parameters=func.get("parameters", {})
                        ))
                if function_declarations:
                    gemini_tools = [types.Tool(function_declarations=function_declarations)]

            # Make the API call
            config_kwargs = {}
            if system_instruction:
                config_kwargs["system_instruction"] = system_instruction

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=gemini_tools,
                    **config_kwargs
                )
            )

            # Parse response
            tool_calls = []
            content = None

            if response.candidates and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        fc = part.function_call
                        tool_calls.append(ToolCall(
                            id=f"call_{fc.name}_{len(tool_calls)}",
                            name=fc.name,
                            arguments=dict(fc.args) if fc.args else {}
                        ))
                    elif hasattr(part, 'text') and part.text:
                        content = part.text

            finish_reason = "tool_calls" if tool_calls else "stop"

            return ChatResponse(
                content=content,
                tool_calls=tool_calls,
                finish_reason=finish_reason,
                raw_response=response
            )

        except Exception as e:
            print(f"Error in Gemini chat_with_tools: {e}")
            # Return error as content
            return ChatResponse(
                content=f"Error: {str(e)}",
                tool_calls=[],
                finish_reason="stop"
            )

class OpenAIClient(BaseLLMClient):
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL")
        model = os.getenv("OPENAI_MODEL", "gpt-4o")

        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set in environment variables.")

        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url

        self.client = OpenAI(**client_kwargs)
        self.model_name = model

    def generate_content(self, prompt: str) -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": "You are a professional financial analyst."},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error generating content with OpenAI: {e}")
            return f"Error: Could not generate analysis. Details: {str(e)}"

    def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_choice: str = "auto"
    ) -> ChatResponse:
        """
        Chat with function calling support for OpenAI/compatible APIs.

        Args:
            messages: Conversation messages in OpenAI format
            tools: List of tool definitions in OpenAI format
            tool_choice: "auto", "none", or "required"

        Returns:
            ChatResponse with content and/or tool_calls
        """
        try:
            # Build request kwargs
            request_kwargs = {
                "model": self.model_name,
                "messages": messages,
            }

            # Add tools if provided
            if tools:
                request_kwargs["tools"] = tools
                request_kwargs["tool_choice"] = tool_choice

            # Make the API call
            response = self.client.chat.completions.create(**request_kwargs)

            # Parse response
            message = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            # Extract reasoning_content for thinking mode models (o1, etc.)
            reasoning_content = getattr(message, 'reasoning_content', None)

            tool_calls = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    # Parse arguments from JSON string
                    try:
                        args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                    except json.JSONDecodeError:
                        args = {}

                    tool_calls.append(ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=args
                    ))

            return ChatResponse(
                content=message.content,
                tool_calls=tool_calls,
                finish_reason="tool_calls" if tool_calls else "stop",
                raw_response=response,
                reasoning_content=reasoning_content
            )

        except Exception as e:
            print(f"Error in OpenAI chat_with_tools: {e}")
            return ChatResponse(
                content=f"Error: {str(e)}",
                tool_calls=[],
                finish_reason="stop"
            )

def get_llm_client() -> BaseLLMClient:
    """
    Factory function to return the configured LLM client.
    """
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()
    
    if provider == "gemini":
        return GoogleGeminiClient()
    elif provider == "openai" or provider == "openai_compatible":
        return OpenAIClient()
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
