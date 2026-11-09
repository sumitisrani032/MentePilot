"""Wire the agents into one graph."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from shopchat.agents.answers import (
    ENGLISH_ONLY_REPLY,
    NO_MATCH_REPLY,
    OUT_OF_SCOPE_REPLY,
    UNCLEAR_REPLY,
    make_detail_answer,
    make_small_talk,
)
from shopchat.agents.router import make_router
from shopchat.agents.select import make_select
from shopchat.agents.state import ChatState, Intent
from shopchat.agents.understand import make_understand
from shopchat.agents.validate import validate_selection
from shopchat.catalog.profile import CatalogProfile
from shopchat.llm.ports import Embedder, LLMBundle
from shopchat.search.types import Candidate, SearchPlan

RetrieveFn = Callable[[UUID, SearchPlan, CatalogProfile, Embedder], Awaitable[list[Candidate]]]
DetailFn = Callable[[UUID, UUID, str, Embedder], Awaitable[list[str]]]
ChatGraph = CompiledStateGraph[ChatState, Any, ChatState, ChatState]

_MAX_RETRIES = 1
_MIN_PICKS = 2


def _after_router(state: ChatState) -> str:
    intent = state["intent"]
    if intent is Intent.SMALL_TALK:
        return "small_talk"
    if intent is Intent.OUT_OF_SCOPE:
        return "out_of_scope"
    if intent is Intent.NON_ENGLISH:
        return "non_english"
    if intent is Intent.UNCLEAR:
        return "unclear"
    if intent is Intent.PRODUCT_DETAIL and state.get("focus_product_id"):
        return "product_detail"
    return "understand"


def _after_understand(state: ChatState) -> str:
    plan = state["plan"]
    return "ask_question" if plan.clarifying_question and not plan.search_phrases else "retrieve"


def _can_retry(state: ChatState) -> bool:
    return state.get("retries", 0) < _MAX_RETRIES


def _after_retrieve(state: ChatState) -> str:
    if state["candidates"]:
        return "select"
    return "loosen" if _can_retry(state) else "no_match"


def _after_validate(state: ChatState) -> str:
    validated = state["validated"]
    wants_more = state["selection"].too_few or len(validated.picks) < _MIN_PICKS
    return "loosen" if wants_more and _can_retry(state) else END


async def _ask_question(state: ChatState) -> dict[str, Any]:
    return {"answer": state["plan"].clarifying_question}


async def _no_match(state: ChatState) -> dict[str, Any]:
    return {"answer": NO_MATCH_REPLY}


async def _out_of_scope(state: ChatState) -> dict[str, Any]:
    return {"answer": OUT_OF_SCOPE_REPLY}


async def _unclear(state: ChatState) -> dict[str, Any]:
    return {"answer": UNCLEAR_REPLY}


async def _non_english(state: ChatState) -> dict[str, Any]:
    return {"answer": ENGLISH_ONLY_REPLY}


async def _loosen(state: ChatState) -> dict[str, Any]:
    """Broaden the search. Price limits stay; other strict filters go only if nothing matched."""
    plan = state["plan"]
    phrases = list(dict.fromkeys([*plan.search_phrases, state["message"]]))
    firm = plan.firm
    if not state.get("candidates"):
        firm = firm.model_copy(update={"facts": {}})
    return {
        "plan": plan.model_copy(
            update={"firm": firm, "soft_preferences": [], "search_phrases": phrases}
        ),
        "retries": state.get("retries", 0) + 1,
    }


async def _validate(state: ChatState) -> dict[str, Any]:
    return {"validated": validate_selection(state["selection"], state["candidates"])}


def build_graph(bundle: LLMBundle, retrieve: RetrieveFn, detail: DetailFn) -> ChatGraph:
    async def retrieve_node(state: ChatState) -> dict[str, Any]:
        found = await retrieve(state["shop_id"], state["plan"], state["profile"], bundle.embedder)
        return {"candidates": found}

    async def detail_node(state: ChatState) -> dict[str, Any]:
        focus = state["focus_product_id"]
        assert focus is not None  # routing only arrives here with a focus product
        chunks = await detail(state["shop_id"], focus, state["message"], bundle.embedder)
        return {"detail_chunks": chunks}

    graph = StateGraph(ChatState)
    graph.add_node("router", make_router(bundle.structured))
    graph.add_node("understand", make_understand(bundle.structured))
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("select", make_select(bundle.structured))
    graph.add_node("validate", _validate)
    graph.add_node("loosen", _loosen)
    graph.add_node("product_detail", detail_node)
    graph.add_node("detail_answer", make_detail_answer(bundle.structured))
    graph.add_node("small_talk", make_small_talk(bundle.streamer))
    graph.add_node("out_of_scope", _out_of_scope)
    graph.add_node("non_english", _non_english)
    graph.add_node("unclear", _unclear)
    graph.add_node("ask_question", _ask_question)
    graph.add_node("no_match", _no_match)

    graph.add_edge(START, "router")
    graph.add_conditional_edges("router", _after_router)
    graph.add_conditional_edges("understand", _after_understand)
    graph.add_conditional_edges("retrieve", _after_retrieve)
    graph.add_edge("select", "validate")
    graph.add_conditional_edges("validate", _after_validate)
    graph.add_edge("loosen", "retrieve")
    graph.add_edge("product_detail", "detail_answer")
    for terminal in ("detail_answer", "small_talk", "out_of_scope", "non_english", "unclear"):
        graph.add_edge(terminal, END)
    graph.add_edge("ask_question", END)
    graph.add_edge("no_match", END)
    return graph.compile()
