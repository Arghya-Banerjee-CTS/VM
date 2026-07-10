import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import AzureOpenAI, OpenAI


BASE_DIR = Path(__file__).resolve().parents[1]
EXCEL_FILE = BASE_DIR / "New Notebooks" / "Live_Dummy_MCP_Traces.xlsx"
SERVER_FILE = BASE_DIR / "scripts" / "dummy_support_mcp_server.py"


SYSTEM_PROMPT = """
You are a careful support assistant. Use the available tools when a task needs
customer, order, policy, refund, or ticket data. After using tools, give a short
answer that explains what you found and what should happen next.
""".strip()


INPUT_COLUMNS = [
    "case_id",
    "case_type",
    "user_input",
    "expected_outcome",
    "expected_tools",
    "expected_notes",
]


STARTER_CASES = [
    {
        "case_id": "CASE-001",
        "case_type": "single_turn",
        "user_input": "Customer C-1002 says their order is late. Check what happened and explain it.",
        "expected_outcome": "The assistant should look up the customer/order, call the order status tool, and explain the delay.",
        "expected_tools": "get_customer_profile,get_order_status",
        "expected_notes": "Positive case: the task requires customer and order lookup.",
    },
    {
        "case_id": "CASE-002",
        "case_type": "single_turn",
        "user_input": "Customer C-1003 wants to know whether order ORD-9003 can be refunded.",
        "expected_outcome": "The assistant should inspect the order, check the refund policy, calculate refund eligibility, and explain the result.",
        "expected_tools": "get_order_status,search_policy_docs,calculate_refund",
        "expected_notes": "Positive case: the task requires policy-aware refund reasoning.",
    },
    {
        "case_id": "CASE-003",
        "case_type": "single_turn",
        "user_input": "Create a support ticket for customer C-1001 because their delivered package arrived damaged.",
        "expected_outcome": "The assistant should look up the customer and create a support ticket with the damaged package issue.",
        "expected_tools": "get_customer_profile,create_support_ticket",
        "expected_notes": "Positive case: the task requires taking an action with a tool.",
    },
]


CUSTOMERS = {
    "C-1001": {
        "customer_id": "C-1001",
        "name": "Anika Sen",
        "tier": "Gold",
        "primary_order_id": "ORD-9001",
        "email": "anika@example.com",
    },
    "C-1002": {
        "customer_id": "C-1002",
        "name": "Rahul Mehta",
        "tier": "Silver",
        "primary_order_id": "ORD-9002",
        "email": "rahul@example.com",
    },
    "C-1003": {
        "customer_id": "C-1003",
        "name": "Maya Rao",
        "tier": "Standard",
        "primary_order_id": "ORD-9003",
        "email": "maya@example.com",
    },
}


ORDERS = {
    "ORD-9001": {
        "order_id": "ORD-9001",
        "customer_id": "C-1001",
        "status": "delivered",
        "item": "Noise cancelling headphones",
        "amount": 199.0,
        "delivered_days_ago": 3,
        "issue": "Customer reports package arrived damaged.",
    },
    "ORD-9002": {
        "order_id": "ORD-9002",
        "customer_id": "C-1002",
        "status": "delayed",
        "item": "Laptop stand",
        "amount": 45.0,
        "delay_reason": "Weather disruption at the regional sorting center.",
        "estimated_delivery": "2026-07-13",
    },
    "ORD-9003": {
        "order_id": "ORD-9003",
        "customer_id": "C-1003",
        "status": "delivered",
        "item": "Smartwatch",
        "amount": 149.0,
        "delivered_days_ago": 42,
        "issue": "Customer asked about refund eligibility.",
    },
}


POLICIES = {
    "refund": {
        "title": "Refund policy",
        "summary": "Most delivered items are refundable within 30 days. Damaged items can be escalated after 30 days for manual review.",
    },
    "delivery": {
        "title": "Delivery delay policy",
        "summary": "If an order is delayed, share the reason and estimated delivery date. Shipping fees may be refunded for delays over 5 days.",
    },
}


TICKETS = []


def get_customer_profile(customer_id):
    return CUSTOMERS.get(customer_id, {"error": f"No customer found for {customer_id}"})


def get_order_status(order_id):
    return ORDERS.get(order_id, {"error": f"No order found for {order_id}"})


def search_policy_docs(query):
    query_text = query.lower()
    matches = []
    for policy_id, policy in POLICIES.items():
        searchable = f"{policy_id} {policy['title']} {policy['summary']}".lower()
        if query_text in searchable or any(word in searchable for word in query_text.split()):
            matches.append({"policy_id": policy_id, **policy})
    return {"query": query, "matches": matches}


def calculate_refund(order_id, reason):
    order = ORDERS.get(order_id)
    if not order:
        return {"order_id": order_id, "eligible": False, "reason": "Order was not found."}

    delivered_days_ago = order.get("delivered_days_ago")
    damaged = "damage" in reason.lower() or "damaged" in order.get("issue", "").lower()

    if delivered_days_ago is not None and delivered_days_ago <= 30:
        return {
            "order_id": order_id,
            "eligible": True,
            "refund_amount": order["amount"],
            "reason": "Order is within the 30 day refund window.",
        }

    if damaged:
        return {
            "order_id": order_id,
            "eligible": "manual_review",
            "refund_amount": None,
            "reason": "Damaged item is outside the standard window and needs manual review.",
        }

    return {
        "order_id": order_id,
        "eligible": False,
        "refund_amount": 0.0,
        "reason": "Order is outside the 30 day refund window.",
    }


def create_support_ticket(customer_id, issue_summary, priority="normal"):
    ticket_id = f"T-{len(TICKETS) + 1001}"
    ticket = {
        "ticket_id": ticket_id,
        "customer_id": customer_id,
        "issue_summary": issue_summary,
        "priority": priority,
        "status": "open",
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    TICKETS.append(ticket)
    return ticket


TOOLS = {
    "get_customer_profile": get_customer_profile,
    "get_order_status": get_order_status,
    "search_policy_docs": search_policy_docs,
    "calculate_refund": calculate_refund,
    "create_support_ticket": create_support_ticket,
}


OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_customer_profile",
            "description": "Get a customer profile by customer ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string", "description": "Customer ID such as C-1002."}
                },
                "required": ["customer_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": "Get order status and order details by order ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Order ID such as ORD-9002."}
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_policy_docs",
            "description": "Search support policy documents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Policy search query."}
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_refund",
            "description": "Calculate refund eligibility for an order.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["order_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_support_ticket",
            "description": "Create a support ticket for a customer issue.",
            "parameters": {
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "issue_summary": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                },
                "required": ["customer_id", "issue_summary", "priority"],
                "additionalProperties": False,
            },
        },
    },
]


DUMMY_SUPPORT_SERVER_OBJECT = '''dummy_support_server = MCPServer(
    server_name="dummy_support",
    transport="stdio",
    available_tools=[
        Tool(
            name="get_customer_profile",
            description="Get a customer profile by customer ID.",
            inputSchema={
                "type": "object",
                "properties": {"customer_id": {"type": "string"}},
                "required": ["customer_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="get_order_status",
            description="Get order status and order details by order ID.",
            inputSchema={
                "type": "object",
                "properties": {"order_id": {"type": "string"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="search_policy_docs",
            description="Search support policy documents.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="calculate_refund",
            description="Calculate refund eligibility for an order.",
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["order_id", "reason"],
                "additionalProperties": False,
            },
        ),
        Tool(
            name="create_support_ticket",
            description="Create a support ticket for a customer issue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "customer_id": {"type": "string"},
                    "issue_summary": {"type": "string"},
                    "priority": {"type": "string", "enum": ["low", "normal", "high"]},
                },
                "required": ["customer_id", "issue_summary", "priority"],
                "additionalProperties": False,
            },
        ),
    ],
)'''


def make_tool_definition_rows():
    rows = []
    for tool in OPENAI_TOOLS:
        function = tool["function"]
        schema = function["parameters"]
        tool_object = (
            "Tool(\n"
            f"    name={function['name']!r},\n"
            f"    description={function['description']!r},\n"
            f"    inputSchema={repr(schema)},\n"
            ")"
        )
        rows.append(
            {
                "tool_name": function["name"],
                "description": function["description"],
                "input_schema_json": json_dumps(schema),
                "tool_object": tool_object,
            }
        )
    return rows


def json_dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def make_call_tool_result_snippet(result):
    result_text = json.dumps(result, ensure_ascii=False)
    return (
        "CallToolResult(\n"
        "    content=[\n"
        "        TextContent(\n"
        "            type=\"text\",\n"
        f"            text={result_text!r}\n"
        "        )\n"
        "    ],\n"
        "    isError=False\n"
        ")"
    )


def make_tool_call_snippet(tool_name, arguments, result):
    result_snippet = make_call_tool_result_snippet(result)
    return (
        "MCPToolCall(\n"
        f"    name={tool_name!r},\n"
        f"    args={repr(arguments)},\n"
        f"    result={result_snippet}\n"
        ")"
    )


def make_test_case_snippet(row, tool_call_snippets, actual_output):
    tools_block = ",\n".join("        " + snippet.replace("\n", "\n        ") for snippet in tool_call_snippets)
    return (
        "LLMTestCase(\n"
        f"    input={row['user_input']!r},\n"
        f"    actual_output={actual_output!r},\n"
        f"    expected_outcome={row['expected_outcome']!r},\n"
        "    mcp_servers=[dummy_support_server],\n"
        "    mcp_tools_called=[\n"
        f"{tools_block}\n"
        "    ],\n"
        ")"
    )


def create_starter_workbook():
    input_df = pd.DataFrame(STARTER_CASES, columns=INPUT_COLUMNS)
    with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl") as writer:
        input_df.to_excel(writer, sheet_name="input_cases", index=False)
    print(f"Created starter workbook: {EXCEL_FILE}")
    print("Add or edit rows in the input_cases sheet, then run this script again.")


def load_input_cases():
    if not EXCEL_FILE.exists():
        create_starter_workbook()

    input_df = pd.read_excel(EXCEL_FILE, sheet_name="input_cases").fillna("")
    missing = [column for column in INPUT_COLUMNS if column not in input_df.columns]
    if missing:
        raise ValueError(f"input_cases is missing columns: {missing}")
    return input_df


def build_client():
    azure_key = os.getenv("AZURE_OPENAI_API_KEY")
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    azure_version = os.getenv("AZURE_OPENAI_API_VERSION")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

    if azure_key and azure_endpoint and azure_version and deployment:
        return AzureOpenAI(api_key=azure_key, azure_endpoint=azure_endpoint, api_version=azure_version), deployment

    model = os.getenv("OPENAI_MODEL", "gpt-5")
    return OpenAI(api_key=os.getenv("OPENAI_API_KEY")), model


def has_llm_credentials():
    has_azure = (
        os.getenv("AZURE_OPENAI_API_KEY")
        and os.getenv("AZURE_OPENAI_ENDPOINT")
        and os.getenv("AZURE_OPENAI_API_VERSION")
        and os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
    )
    return bool(os.getenv("OPENAI_API_KEY") or has_azure)


def result_from_mcp_call(call_result):
    if getattr(call_result, "structuredContent", None):
        return call_result.structuredContent

    text_parts = []
    for content_item in getattr(call_result, "content", []):
        text = getattr(content_item, "text", None)
        if text:
            text_parts.append(text)

    joined_text = "\n".join(text_parts)
    if not joined_text:
        return {}

    try:
        return json.loads(joined_text)
    except json.JSONDecodeError:
        return {"content": joined_text}


async def run_case(client, model_name, row, mcp_session):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": row["user_input"]},
    ]
    tool_trace_rows = []
    tool_call_snippets = []

    for step_index in range(8):
        response = client.chat.completions.create(
            model=model_name,
            messages=messages,
            tools=OPENAI_TOOLS,
            tool_choice="auto",
        )
        assistant_message = response.choices[0].message

        if not assistant_message.tool_calls:
            return assistant_message.content or "", tool_trace_rows, tool_call_snippets

        messages.append(assistant_message)

        for tool_index, tool_call in enumerate(assistant_message.tool_calls, start=1):
            tool_name = tool_call.function.name
            arguments = json.loads(tool_call.function.arguments or "{}")
            mcp_result = await mcp_session.call_tool(tool_name, arguments)
            result = result_from_mcp_call(mcp_result)
            result_text = json.dumps(result, ensure_ascii=False)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": result_text,
                }
            )

            snippet = make_tool_call_snippet(tool_name, arguments, result)
            tool_call_snippets.append(snippet)
            tool_trace_rows.append(
                {
                    "case_id": row["case_id"],
                    "turn_index": 1,
                    "tool_call_index": len(tool_trace_rows) + 1,
                    "llm_step_index": step_index + 1,
                    "tool_name": tool_name,
                    "tool_arguments_json": json_dumps(arguments),
                    "tool_result_json": json_dumps(result),
                    "mcp_tool_call_object": snippet,
                }
            )

    return "The model did not finish within the tool-call step limit.", tool_trace_rows, tool_call_snippets


async def main():
    input_df = load_input_cases()

    if not has_llm_credentials():
        print("No LLM credentials found.")
        print(f"The input workbook is ready here: {EXCEL_FILE}")
        print("Set OpenAI or Azure OpenAI environment variables, then run this script again.")
        return

    client, model_name = build_client()

    output_rows = []
    all_tool_rows = []
    object_rows = []

    server_params = StdioServerParameters(command=sys.executable, args=[str(SERVER_FILE)])
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as mcp_session:
            await mcp_session.initialize()

            for _, row in input_df.iterrows():
                row = row.to_dict()
                print(f"Running {row['case_id']}: {row['user_input']}")
                actual_output, tool_rows, tool_call_snippets = await run_case(client, model_name, row, mcp_session)
                all_tool_rows.extend(tool_rows)

                tools_called = ",".join(tool_row["tool_name"] for tool_row in tool_rows)
                test_case_snippet = make_test_case_snippet(row, tool_call_snippets, actual_output)

                output_rows.append(
                    {
                        "case_id": row["case_id"],
                        "case_type": row["case_type"],
                        "user_input": row["user_input"],
                        "expected_outcome": row["expected_outcome"],
                        "expected_tools": row["expected_tools"],
                        "actual_output": actual_output,
                        "tools_called": tools_called,
                        "tool_call_count": len(tool_rows),
                        "run_status": "completed",
                    }
                )

                object_rows.append(
                    {
                        "case_id": row["case_id"],
                        "dummy_mcp_server_object": DUMMY_SUPPORT_SERVER_OBJECT,
                        "mcp_tool_call_objects": "\n\n".join(tool_call_snippets),
                        "llm_test_case_object": test_case_snippet,
                    }
                )

    with pd.ExcelWriter(EXCEL_FILE, engine="openpyxl", mode="w") as writer:
        input_df.to_excel(writer, sheet_name="input_cases", index=False)
        pd.DataFrame(make_tool_definition_rows()).to_excel(writer, sheet_name="tool_definitions", index=False)
        pd.DataFrame(output_rows).to_excel(writer, sheet_name="llm_outputs", index=False)
        pd.DataFrame(all_tool_rows).to_excel(writer, sheet_name="tool_calls", index=False)
        pd.DataFrame(object_rows).to_excel(writer, sheet_name="deepeval_objects", index=False)

    print(f"Done. Wrote traces to: {EXCEL_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
