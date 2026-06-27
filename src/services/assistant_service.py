"""
AI Assistant Service - Context-aware chat assistant with Function Calling

Provides intelligent chat functionality that:
- Dynamically decides which tools to call based on user questions
- Executes tool calls to fetch real-time data
- Generates enhanced responses using LLM with tool results
"""

import json
import re
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from src.llm.client import get_llm_client, ChatResponse, ToolCall
from src.llm.tools.schemas import get_tools_for_llm
from src.llm.tools.executor import tool_executor
from src.services.news_service import news_service
from src.storage.db import get_all_stocks, get_all_funds


# System prompt for the AI assistant
SYSTEM_PROMPT = """你是一个专业的金融投资助手。你可以使用提供的工具获取实时市场数据来回答用户的问题。

重要规则：
1. 当用户询问股票价格、涨跌等实时数据时，必须先调用相应的工具获取数据
2. 当用户询问市场行情、板块表现、资金流向等时，调用对应的工具
3. 当用户询问新闻、消息时，调用新闻相关的工具
4. 如果问题不需要实时数据，可以直接回答
5. 回答要简洁专业，使用中文
6. 如果工具返回错误或无数据，诚实告知用户
7. 投资建议需要提示风险

股票代码说明：
- A股代码为6位数字，如600519（贵州茅台）、000001（平安银行）
- 常见股票：茅台=600519、平安银行=000001、中国平安=601318、招商银行=600036、宁德时代=300750"""


@dataclass
class IntentResult:
    """Result of intent analysis"""
    intent_type: str  # 'news', 'data', 'analysis', 'general'
    keywords: List[str]
    sentiment_filter: Optional[str] = None  # 'positive', 'negative', None


class AssistantService:
    """
    Context-aware AI Assistant Service with Function Calling

    Features:
    - Dynamic tool selection based on user questions
    - Agent Loop for multi-turn tool execution
    - Context injection from current page/stock/fund
    - Multi-turn conversation support
    """

    def __init__(self):
        self._llm_client = None
        self._max_iterations = 5  # Maximum Agent Loop iterations
        self._tool_timeout = 10  # Seconds per tool call

    def _get_llm_client(self):
        """Lazy initialization of LLM client"""
        if self._llm_client is None:
            try:
                self._llm_client = get_llm_client()
            except Exception as e:
                print(f"Warning: LLM client initialization failed: {e}")
        return self._llm_client

    def _analyze_intent(self, message: str) -> IntentResult:
        """
        Analyze user intent from message for backward compatibility.

        Categories:
        - news: News, announcements, information queries
        - data: Price, volume, PE, market data queries
        - analysis: Analysis, opinions, suggestions
        - general: General conversation
        """
        message_lower = message.lower()

        # Intent keywords mapping
        intent_keywords = {
            "news": [
                "新闻", "消息", "资讯", "利好", "利空", "公告", "通知",
                "发生", "最近", "动态", "事件", "报道", "披露"
            ],
            "data": [
                "价格", "股价", "市值", "涨跌", "涨", "跌", "成交量", "成交额",
                "pe", "pb", "市盈率", "市净率", "roe", "净值",
                "多少钱", "现价", "收盘", "开盘", "最高", "最低",
                "北向", "资金", "板块", "行情", "指数", "大盘", "流入", "流出"
            ],
            "analysis": [
                "分析", "看法", "建议", "怎么看", "前景", "预测",
                "机会", "风险", "走势", "趋势", "能买", "该卖",
                "估值", "投资", "策略"
            ]
        }

        # Sentiment keywords
        positive_keywords = ["利好", "上涨", "机会", "买入", "看多"]
        negative_keywords = ["利空", "下跌", "风险", "卖出", "看空"]

        # Detect intent
        detected_intent = "general"
        matched_keywords = []

        for intent_type, keywords in intent_keywords.items():
            for keyword in keywords:
                if keyword in message_lower:
                    detected_intent = intent_type
                    matched_keywords.append(keyword)

        # Detect sentiment filter
        sentiment_filter = None
        if any(kw in message_lower for kw in positive_keywords):
            sentiment_filter = "positive"
        elif any(kw in message_lower for kw in negative_keywords):
            sentiment_filter = "negative"

        return IntentResult(
            intent_type=detected_intent,
            keywords=matched_keywords[:5],  # Limit keywords
            sentiment_filter=sentiment_filter
        )

    def chat(
        self,
        message: str,
        context: Dict[str, Any],
        history: List[Dict[str, str]],
        user_id: int = 1
    ) -> Dict[str, Any]:
        """
        Process a chat message with function calling support.

        Args:
            message: User's message
            context: Current context (page, stock, fund)
            history: Conversation history
            user_id: User ID for personalized data

        Returns:
            Dict with response, sources, and context_used (backward compatible)
        """
        # Analyze intent for backward compatibility
        intent = self._analyze_intent(message)

        llm = self._get_llm_client()
        if not llm:
            return {
                "response": "AI服务暂时不可用，请稍后重试。",
                "sources": [],
                "context_used": {
                    "stock_code": context.get("stock", {}).get("code") if context.get("stock") else None,
                    "fund_code": context.get("fund", {}).get("code") if context.get("fund") else None,
                    "intent": intent.intent_type,
                    "search_keywords": intent.keywords,
                }
            }

        try:
            # Run the Agent Loop
            response, tools_used = self._run_agent_loop(message, context, history)

            # Clean up response
            response = self._clean_response(response)

            # Build context_used with backward compatibility
            context_used = {
                "stock_code": context.get("stock", {}).get("code") if context.get("stock") else None,
                "fund_code": context.get("fund", {}).get("code") if context.get("fund") else None,
                "intent": intent.intent_type,
                "search_keywords": intent.keywords,
                "tools_used": tools_used,  # New field for function calling
            }

            return {
                "response": response,
                "sources": [],  # Sources are now fetched via tools, not pre-searched
                "context_used": context_used
            }
        except Exception as e:
            print(f"Assistant chat error: {e}")
            import traceback
            traceback.print_exc()
            return {
                "response": "抱歉，处理您的请求时出现错误。请稍后重试。",
                "sources": [],
                "context_used": {
                    "stock_code": context.get("stock", {}).get("code") if context.get("stock") else None,
                    "fund_code": context.get("fund", {}).get("code") if context.get("fund") else None,
                    "intent": intent.intent_type,
                    "search_keywords": intent.keywords,
                }
            }

    def _run_agent_loop(
        self,
        message: str,
        context: Dict[str, Any],
        history: List[Dict[str, str]]
    ) -> tuple:
        """
        Run the Agent Loop with function calling.

        Returns:
            Tuple of (response_text, tools_used_list)
        """
        llm = self._get_llm_client()
        provider = os.getenv("LLM_PROVIDER", "gemini").lower()

        # Build initial messages
        messages = self._build_messages(message, context, history)

        # Get tools in provider format
        tools = get_tools_for_llm(provider)

        tools_used = []
        reasoning_content = None  # Track reasoning_content for thinking mode models

        for iteration in range(self._max_iterations):
            print(f"[Agent Loop] Iteration {iteration + 1}")

            # Call LLM with tools
            response: ChatResponse = llm.chat_with_tools(
                messages=messages,
                tools=tools,
                tool_choice="auto"
            )

            print(f"[Agent Loop] finish_reason: {response.finish_reason}, tool_calls: {len(response.tool_calls)}")

            # Capture reasoning_content for thinking mode models (o1, etc.)
            if response.reasoning_content:
                reasoning_content = response.reasoning_content
                print(f"[Agent Loop] Captured reasoning_content ({len(reasoning_content)} chars)")

            # Check if we have tool calls
            if response.tool_calls:
                # Execute each tool call
                for tool_call in response.tool_calls:
                    print(f"[Agent Loop] Executing tool: {tool_call.name} with args: {tool_call.arguments}")

                    # Execute the tool
                    result = tool_executor.execute(tool_call.name, tool_call.arguments)

                    tools_used.append({
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                        "success": result.get("success", False)
                    })

                    # Build assistant message with tool call (for OpenAI format)
                    assistant_msg = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.name,
                                "arguments": json.dumps(tool_call.arguments, ensure_ascii=False)
                            }
                        }]
                    }

                    # Include reasoning_content for thinking mode models
                    if reasoning_content and provider in ["openai", "openai_compatible"]:
                        assistant_msg["reasoning_content"] = reasoning_content
                        reasoning_content = None  # Clear after use

                    messages.append(assistant_msg)

                    # Add tool result message
                    if provider in ["openai", "openai_compatible"]:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result.get("data") or result, ensure_ascii=False)
                        })
                    else:
                        # Gemini format
                        messages.append({
                            "role": "tool",
                            "name": tool_call.name,
                            "content": json.dumps(result.get("data") or result, ensure_ascii=False)
                        })

                # Continue the loop to get next response
                continue

            # No tool calls - we have a final response
            if response.content:
                return response.content, tools_used

            # No content and no tool calls - something went wrong
            return "抱歉，我无法处理您的请求。请稍后重试。", tools_used

        # Reached max iterations
        return "抱歉，处理您的请求时超过了最大步骤数。请尝试简化您的问题。", tools_used

    def _build_messages(
        self,
        message: str,
        context: Dict[str, Any],
        history: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """
        Build the messages list for the LLM.

        Returns:
            List of messages in OpenAI format
        """
        messages = []

        # System prompt with context
        system_content = SYSTEM_PROMPT

        # Add current context to system prompt
        stock = context.get("stock")
        fund = context.get("fund")

        if stock or fund:
            system_content += "\n\n【当前上下文】"
            if stock:
                system_content += f"\n用户正在查看股票: {stock.get('name', '')} (代码: {stock.get('code', '')})"
            if fund:
                system_content += f"\n用户正在查看基金: {fund.get('name', '')} (代码: {fund.get('code', '')})"

        messages.append({
            "role": "system",
            "content": system_content
        })

        # Add conversation history (last 5 turns)
        for turn in history[-5:]:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ["user", "assistant"] and content:
                messages.append({
                    "role": role,
                    "content": content
                })

        # Add current user message
        messages.append({
            "role": "user",
            "content": message
        })

        return messages

    def _clean_response(self, response: str) -> str:
        """Clean up LLM response"""
        if not response:
            return "抱歉，我无法生成回答。请稍后重试。"

        # Remove thinking/reasoning tags (various formats)
        response = re.sub(r'<think(?:ing)?>\s*[\s\S]*?\s*</think(?:ing)?>', '', response, flags=re.IGNORECASE)
        response = re.sub(r'<reason(?:ing)?>\s*[\s\S]*?\s*</reason(?:ing)?>', '', response, flags=re.IGNORECASE)

        # Remove any remaining unclosed thinking tags at the start
        response = re.sub(r'^<think(?:ing)?>\s*', '', response, flags=re.IGNORECASE)
        response = re.sub(r'\s*</think(?:ing)?>$', '', response, flags=re.IGNORECASE)

        # Remove any markdown code blocks
        response = re.sub(r'^```.*?\n', '', response)
        response = re.sub(r'\n```$', '', response)

        # Clean up excessive whitespace
        response = re.sub(r'\n{3,}', '\n\n', response)

        return response.strip()

    def get_suggested_questions(self, context: Dict[str, Any]) -> List[str]:
        """
        Get suggested questions based on current context.

        Useful for quick-start prompts in the UI.
        """
        suggestions = []

        stock = context.get("stock")
        fund = context.get("fund")
        page = context.get("page", "")

        if stock:
            name = stock.get("name", "这只股票")
            suggestions.extend([
                f"{name}现在多少钱？",
                f"{name}最近有什么新闻？",
                f"分析一下{name}的投资价值",
                "今天北向资金流入多少？",
            ])
        elif fund:
            name = fund.get("name", "这只基金")
            suggestions.extend([
                f"{name}的业绩表现如何？",
                f"{name}的投资风格是什么？",
                f"分析一下{name}的持仓",
                "今天市场行情怎么样？",
            ])
        else:
            # General suggestions based on page
            if page == "stocks":
                suggestions.extend([
                    "今天大盘怎么样？",
                    "哪些板块涨幅最大？",
                    "北向资金今天流入多少？",
                    "茅台现在多少钱？",
                ])
            elif page == "funds":
                suggestions.extend([
                    "最近哪类基金表现较好？",
                    "今天市场行情如何？",
                    "有什么热门新闻？",
                    "主力资金流向哪里？",
                ])
            elif page == "news":
                suggestions.extend([
                    "今天有什么重要新闻？",
                    "市场有什么热点？",
                    "北向资金动向如何？",
                    "哪些板块表现最好？",
                ])
            else:
                suggestions.extend([
                    "今天大盘怎么样？",
                    "北向资金流入多少？",
                    "哪些板块涨幅最大？",
                    "有什么热门新闻？",
                ])

        return suggestions[:4]


# Singleton instance
assistant_service = AssistantService()
