from datetime import datetime

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("dummy_support")


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


@mcp.tool()
def get_customer_profile(customer_id: str) -> dict:
    """Get a customer profile by customer ID."""
    return CUSTOMERS.get(customer_id, {"error": f"No customer found for {customer_id}"})


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """Get order status and order details by order ID."""
    return ORDERS.get(order_id, {"error": f"No order found for {order_id}"})


@mcp.tool()
def search_policy_docs(query: str) -> dict:
    """Search support policy documents."""
    query_text = query.lower()
    matches = []
    for policy_id, policy in POLICIES.items():
        searchable = f"{policy_id} {policy['title']} {policy['summary']}".lower()
        if query_text in searchable or any(word in searchable for word in query_text.split()):
            matches.append({"policy_id": policy_id, **policy})
    return {"query": query, "matches": matches}


@mcp.tool()
def calculate_refund(order_id: str, reason: str) -> dict:
    """Calculate refund eligibility for an order."""
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


@mcp.tool()
def create_support_ticket(customer_id: str, issue_summary: str, priority: str = "normal") -> dict:
    """Create a support ticket for a customer issue."""
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


if __name__ == "__main__":
    mcp.run(transport="stdio")
