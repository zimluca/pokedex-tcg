from agent import Agent

if __name__ == "__main__":
    agent = Agent()
    prompt = input("Inserisci il tuo prompt: ")
    response = agent.respond(prompt)
    print("Risposta dell'agente:", response)
