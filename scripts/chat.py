"""
CHAT WITH THE AI CARE ASSISTANT

Ask questions about the cases in one region and about the law. The assistant
remembers the conversation, so follow-up questions such as "this case" or
"explain further" work. Write names with a capital letter.
"""

from __future__ import annotations

import sys

import requests

from app.llm.client import check_ollama
from app.services import chat_store
from app.tools.assistant import Reply, chat_stream


def show_answer(items) -> Reply:
    """Print the answer as it is written; return the checked reply."""
    print("\nAI CARE Assistant:")
    streamed = False
    for item in items:
        if isinstance(item, Reply):
            if not streamed and not item.needs_approval:
                print(item.text, end="")          # nothing was streamed: print the whole answer
            return item
        streamed = True
        print(item, end="", flush=True)


def run_chat(region: str | None) -> None:
    """The chat: type a question, get the answer, until /exit. region None = all regions."""
    if not check_ollama():
        print("\nOllama is not running.")
        return

    print("\nOllama is running.")

    conversation = chat_store.create_conversation()

    who = region or "all regions (super administrator)"
    print(f"\nAI CARE Assistant (region: {who}):")
    print("Type /exit to stop.")
    print("Type /reset to clear the conversation.")
    print("Type /history to view the conversation.")
    print("Write names with a capital letter.\n")

    while True:
        prompt = input("You: ").strip()

        if not prompt:
            print("Please enter a message.")
            continue

        command = prompt.lower()

        if command == "/exit":
            print("Goodbye!")
            break

        if command == "/reset":
            conversation = chat_store.clear_conversation(conversation)
            print("\nConversation reset.\n")
            continue

        if command == "/history":
            for message in chat_store.show_history(conversation):
                print(f"{message['role']}: {message['content']}")
            print()
            continue

        try:
            reply = show_answer(chat_stream(conversation, prompt, region))

            # Finding a case by name needs the user's OK first.
            if reply.needs_approval:
                print(reply.text)
                if input("Continue? (yes/no): ").strip().lower() not in ("yes", "y"):
                    print("Not searched.\n")
                    continue
                reply = show_answer(chat_stream(conversation, prompt, region, approved=reply.needs_approval))

        except requests.exceptions.ConnectionError:
            print("\nERROR: Could not connect to Ollama.")
            continue

        except requests.exceptions.RequestException as error:
            print(f"\nAPI ERROR: {error}")
            continue

        print(reply.with_sources()[len(reply.text):])      # sources and counts, after the streamed answer
        print()


if __name__ == "__main__":
    choice = sys.argv[1] if len(sys.argv) > 1 else "northern"
    run_chat(None if choice == "all" else choice)
