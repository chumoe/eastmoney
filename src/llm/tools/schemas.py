"""
Tool Schemas for AI Assistant Function Calling

Defines tool schemas for OpenAI-compatible function calling format.
These tools allow the AI to dynamically fetch data based on user questions.
"""

from typing import List, Dict, Any


# Tool schema definitions following OpenAI function calling format
TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "get_stock_quote": {
        "description": "获取股票实时行情数据。当用户询问股票价格、涨跌、成交量时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码，6位数字，如600519（茅台）、000001（平安银行）"
                }
            },
            "required": ["stock_code"]
        }
    },

    "get_stock_history": {
        "description": "获取股票历史K线数据。当用户询问股票历史走势、过去表现时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码，6位数字"
                },
                "days": {
                    "type": "integer",
                    "description": "获取最近多少天的数据，默认30天",
                    "default": 30
                }
            },
            "required": ["stock_code"]
        }
    },

    "get_market_indices": {
        "description": "获取大盘指数数据（上证指数、深证成指、创业板等）。当用户询问大盘、指数、市场整体表现时使用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    "get_northbound_flow": {
        "description": "获取北向资金（沪深港通）流入流出数据。当用户询问北向资金、外资、港资流入流出时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "获取最近多少天的数据，默认5天",
                    "default": 5
                }
            },
            "required": []
        }
    },

    "get_industry_flow": {
        "description": "获取行业资金流向数据。当用户询问哪些行业资金流入流出、行业资金排名时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10个",
                    "default": 10
                }
            },
            "required": []
        }
    },

    "get_main_capital_flow": {
        "description": "获取主力资金流向排行。当用户询问主力资金、大单资金流入哪些股票时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10个",
                    "default": 10
                }
            },
            "required": []
        }
    },

    "get_sector_performance": {
        "description": "获取板块涨跌幅排行。当用户询问哪些板块涨幅最大、板块表现、概念板块时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10个",
                    "default": 10
                }
            },
            "required": []
        }
    },

    "get_top_list": {
        "description": "获取龙虎榜数据。当用户询问龙虎榜、游资动向、机构买卖时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10个",
                    "default": 10
                }
            },
            "required": []
        }
    },

    "get_forex_rates": {
        "description": "获取外汇汇率数据。当用户询问汇率、美元人民币、外汇时使用。",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    "get_stock_news": {
        "description": "获取股票相关新闻。当用户询问某只股票的新闻、消息、公告时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "stock_code": {
                    "type": "string",
                    "description": "股票代码，6位数字"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10条",
                    "default": 10
                }
            },
            "required": ["stock_code"]
        }
    },

    "get_hot_news": {
        "description": "获取市场热门新闻。当用户询问今天新闻、市场消息、有什么热点时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10条",
                    "default": 10
                }
            },
            "required": []
        }
    },

    "search_research_reports": {
        "description": "搜索研究报告。当用户询问研报、分析师观点、机构研究时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，如股票名称、行业名称"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认5条",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },

    "get_fund_info": {
        "description": "获取基金详细信息，包括净值、涨跌幅、规模等。当用户询问基金净值、基金表现、ETF信息时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "fund_code": {
                    "type": "string",
                    "description": "基金代码，6位数字，如016708、000001"
                }
            },
            "required": ["fund_code"]
        }
    },

    "get_fund_holdings": {
        "description": "获取基金持仓信息（重仓股）。当用户询问基金持有哪些股票、基金重仓股时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "fund_code": {
                    "type": "string",
                    "description": "基金代码，6位数字"
                }
            },
            "required": ["fund_code"]
        }
    },

    "search_funds": {
        "description": "搜索基金。当用户询问某类基金、查找基金时使用。支持按名称或代码模糊搜索。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，如基金名称、代码或类型（如'有色金属'、'医疗'、'沪深300'）"
                },
                "limit": {
                    "type": "integer",
                    "description": "返回数量，默认10个",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },

    "run_portfolio_stress_test": {
        "description": "对投资组合运行压力测试。当用户询问'如果...会怎样'、'利率上升/下降影响'、'汇率变化对组合影响'等风险情景问题时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "portfolio_id": {
                    "type": "integer",
                    "description": "组合ID（从上下文获取）"
                },
                "interest_rate_change_bp": {
                    "type": "number",
                    "description": "利率变化（基点），如加息75个基点填75，降息50个基点填-50"
                },
                "fx_change_pct": {
                    "type": "number",
                    "description": "汇率变化（百分比），人民币贬值3%填-3，升值2%填2"
                },
                "index_change_pct": {
                    "type": "number",
                    "description": "指数/大盘变化（百分比），下跌8%填-8，上涨5%填5"
                },
                "oil_change_pct": {
                    "type": "number",
                    "description": "油价变化（百分比），上涨15%填15，下跌10%填-10"
                }
            },
            "required": ["portfolio_id"]
        }
    }
}


def get_tools_for_llm(provider: str = "openai") -> List[Dict[str, Any]]:
    """
    Convert tool schemas to LLM provider format.

    Args:
        provider: LLM provider name ('openai', 'openai_compatible', or 'gemini')

    Returns:
        List of tool definitions in provider-specific format
    """
    # Always use OpenAI format with "type": "function" for compatibility
    # Most providers (including Gemini via API, OpenAI-compatible APIs) require this
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": schema["description"],
                "parameters": schema["parameters"]
            }
        }
        for name, schema in TOOL_SCHEMAS.items()
    ]


def get_tool_names() -> List[str]:
    """Get list of all available tool names."""
    return list(TOOL_SCHEMAS.keys())


def get_tool_description(tool_name: str) -> str:
    """Get description for a specific tool."""
    if tool_name in TOOL_SCHEMAS:
        return TOOL_SCHEMAS[tool_name]["description"]
    return ""
