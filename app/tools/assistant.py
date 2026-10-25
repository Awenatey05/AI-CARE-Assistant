"""The assistant: the model chooses tools, Python runs them, the model answers.

    question -> model: {"tool": ..., "args": ...} -> Tool.invoke (Pydantic check) -> Python -> result -> model
             -> ... (within the budget) -> model: {"answer": ...} -> citation check -> reply

Numbers and verdicts come from the case tools (the assessment made at intake),
never from the model. A wrong argument, an unknown tool or a reply that is
not JSON is sent back to the model to correct, until the budget runs out.
A tool that needs the user's OK (finding a case by name) stops the loop and
asks first. The tools are made for the user's region only.

The question is masked first, like every text the model reads: it sees [NAME]
and [PHONE], never a name or number. A name the user asks about stays in
Python and is put back only when finding a case by name, after the user's OK.

The model is small (llama3.2), so three things do not rely on it:
    - a case reference in the question is looked up by Python before the model starts;
    - empty values ("all", "any") are removed and "high risk" is read as High;
    - the sources every tool returned are listed under the answer, even if the model cites none.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, get_args

from pydantic import ValidationError

from app.llm.client import chat_with_llm, parse_json_object
from app.rag.answer import NO_EVIDENCE, cited_labels
from app.services.masking import mask_keeping_names
from app.tools.agents import AgentState, Tool, enforce_budget
from app.tools.case_tools import make_case_tools
from app.tools.search_tool import make_search_tool

# 1. INSTRUCTIONS
COULD_NOT_FINISH = "I could not finish this; please ask in a simpler way."

INSTRUCTIONS = """You are the AI CARE Assistant for child-protection staff in Ghana.
You answer questions about the cases in the user's region and about the law, using ONLY the tools below.

RULES:
- For every number, list, verdict or reason, call a tool. Never guess or count yourself.
- Answer only from the tool results. If they do not answer the question, say: I don't have enough evidence.
- Cite every case reference and evidence label you use in square brackets, e.g. [NR-TML-GUM-0012-2026] or
  [policy_childrens_act_560.pdf#chunk-16]. Do not invent references or labels.
- Never write a child's name, a phone number or other personal details. If a report has a phone number or
  photos, say so and tell the user to open the case in the dashboard.
- A band, indicator or alert was decided when the case was assessed; report it with its quote, do not judge again.

- Give only the arguments the question asks for. Leave out every other argument.
- If the question names a case reference, use show_case (its result may already be given below).
- A place (village, town or district) goes in "place".

TOOLS:
{tools}

Reply with ONE JSON object only, either
  {{"tool": "<tool name>", "args": {{...}}}}   to use a tool, or
  {{"answer": "<your answer to the user>"}}     when you can answer.

EXAMPLES:
Question: How many high risk cases are there?
  {{"tool": "count_cases", "args": {{"band": "High"}}}}
  (result: total 26)
  {{"answer": "There are 26 High-risk cases in your region."}}
Question: Which children in Gumani are out of school?
  {{"tool": "list_cases", "args": {{"place": "Gumani", "indicator": 7}}}}
  (result: NR-TML-GUM-0002-2025, Low, quote "He misses school most weeks.")
  {{"answer": "One child: [NR-TML-GUM-0002-2025] (Low), out of school: \"He misses school most weeks.\""}}
Question: What does the law say about child labour at night?
  {{"tool": "search_documents", "args": {{"question": "child labour at night", "only": "policy"}}}}
  (result: label policy_childrens_act_560.pdf#chunk-89, "No person shall engage a child in night work.")
  {{"answer": "The Children's Act forbids night work by children [policy_childrens_act_560.pdf#chunk-89]."}}
"""


def choices(tool: Tool, name: str) -> list[str]:
    """The allowed values of an argument that has a fixed list (band, channel, status)."""
    annotation = tool.args_model.model_fields[name].annotation
    for part in get_args(annotation) or (annotation,):
        values = get_args(part)
        if values and all(isinstance(v, str) for v in values):
            return list(values)
    return []


def describe_tools(tools: dict[str, Tool]) -> str:
    lines = []
    for tool in tools.values():
        args = []
        for name, info in tool.args_model.model_fields.items():
            allowed = choices(tool, name)
            hint = "one of: " + ", ".join(allowed) if allowed else (info.description or "")
            args.append(f"{name} ({hint})" if hint else name)
        lines.append(f"- {tool.name}: {tool.description} Arguments, all optional unless needed: "
                     f"{'; '.join(args) or 'none'}.")
    return "\n".join(lines)


# 2. GUARDS (the parts that do not rely on the model)
REFERENCE = re.compile(r"\b[A-Z]{2,3}(?:-[A-Z0-9]{2,6}){1,2}-\d{4}-\d{4}\b")
EMPTY = {"", "all", "any", "none", "null", "n/a", "*"}


def clean_args(tool: Tool, args: dict[str, Any]) -> dict[str, Any]:
    """Remove empty values and arguments the tool does not have; read "high risk" as High."""
    cleaned = {}
    for name, value in args.items():
        if name not in tool.args_model.model_fields or value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value.lower() in EMPTY:
                continue
            allowed = choices(tool, name)
            plain = value.lower().replace(" risk", "").replace("_", " ")
            value = next((a for a in allowed if a.lower() == plain), value)
            if tool.args_model.model_fields[name].annotation in (int, int | None) and not value.isdigit():
                continue        # e.g. "1-10" means any indicator
        cleaned[name] = value
    return cleaned


# 3. THE RESULT
@dataclass
class Reply:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    invented_citations: list[str] = field(default_factory=list)
    needs_approval: dict[str, Any] | None = None     # the tool call waiting for the user's OK
    stopped_reason: str | None = None
    sources: list[str] = field(default_factory=list)  # every reference and label the tools returned

    def with_sources(self) -> str:
        shown = self.citations or self.sources[:10]
        return self.text + ("\n\nSources: " + ", ".join(f"[{s}]" for s in shown) if shown else "")


def references_in(result: Any) -> set[str]:
    """Every case reference and evidence label a tool returned: the only labels an answer may cite."""
    found: set[str] = set()
    if isinstance(result, dict):
        for key, value in result.items():
            if key in ("case_ref", "label") and isinstance(value, str):
                found.add(value)
            else:
                found |= references_in(value)
    elif isinstance(result, list):
        for item in result:
            found |= references_in(item)
    return found


# 4. THE LOOP
def ask(question: str, region: str | None, *, approved: dict[str, Any] | None = None,
        history: list[dict[str, str]] | None = None) -> Reply:
    """Answer one question for a user of `region`. `approved` is a tool call the user has said OK to."""
    references = REFERENCE.findall(question.upper())      # found before masking, so a reference is never lost
    question, names = mask_keeping_names(question)        # the model only ever sees [NAME] and [PHONE]
    tools = {tool.name: tool for tool in make_case_tools(region) + [make_search_tool(region)]}
    state = AgentState(messages=[{"role": "system", "content": INSTRUCTIONS.format(tools=describe_tools(tools))},
                                 *(history or []), {"role": "user", "content": question}])
    calls: list[dict[str, Any]] = []
    allowed: set[str] = set()
    sources: list[str] = []

    def run(name: str, args: dict[str, Any], *, ok: bool = False, shown: dict[str, Any] | None = None) -> Any:
        state.tool_calls += 1
        result = tools[name].invoke(args, approved=ok)
        calls.append({"tool": name, "args": shown if shown is not None else args})   # never a real name
        found = references_in(result)
        allowed.update(found)
        sources.extend(sorted(f for f in found if f not in sources))
        state.messages.append({"role": "user", "content": f"TOOL RESULT ({name}):\n"
                               f"{json.dumps(result, default=str, ensure_ascii=False)}"})
        return result

    for reference in dict.fromkeys(references):                              # guard: look it up first
        run("show_case", {"case_ref": reference})

    while True:
        try:
            enforce_budget(state)
        except RuntimeError as reason:
            return Reply(COULD_NOT_FINISH, calls, stopped_reason=str(reason), sources=sources)
        state.steps += 1
        reply = chat_with_llm(state.messages, format="json")
        state.messages.append({"role": "assistant", "content": reply.text})
        try:
            choice = parse_json_object(reply.text)
        except ValueError:
            state.messages.append({"role": "user", "content": "Reply with ONE JSON object only."})
            continue

        if "answer" in choice:
            text = str(choice["answer"]).strip() or NO_EVIDENCE
            citations = cited_labels(text)
            return Reply(text, calls, citations, [c for c in citations if c not in allowed], sources=sources)

        name, args = choice.get("tool"), choice.get("args") or {}
        if name in tools:
            args = clean_args(tools[name], args)
        if name not in tools:
            state.messages.append({"role": "user", "content": f"There is no tool called {name!r}. "
                                   f"Use one of: {', '.join(tools)}."})
            continue
        tool = tools[name]
        if tool.requires_approval and approved != {"tool": name, "args": args}:
            return Reply(f"This looks up a child's name ({name}). Continue?", calls,
                         needs_approval={"tool": name, "args": args}, sources=sources)
        real_args = args
        if name == "find_case_by_name" and names and "[NAME]" in str(args.get("name", "")):
            real_args = {**args, "name": " ".join(names)}  # the real name goes to the database, not the model
        try:
            run(name, real_args, ok=tool.requires_approval, shown=args)
        except ValidationError as error:
            problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors())
            state.messages.append({"role": "user", "content": f"The arguments for {name} were wrong ({problems}). "
                                   "Correct them and try again."})
            calls.append({"tool": name, "args": args, "error": problems})
