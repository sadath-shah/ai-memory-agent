def run_cli(agent):
    print("AI Memory Agent started!")
    print("Commands: 'show my memories', 'update memory', 'delete memory', 'exit'\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            return
        if not user_input:
            continue
        if user_input.lower() == "exit":
            print("Goodbye!")
            return
        print("Agent:", agent.handle(user_input).text, "\n")
