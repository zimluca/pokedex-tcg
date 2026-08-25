import openai

class Agent:
    def __init__(self):
        # Inizializza l'agente con le credenziali di OpenAI
        openai.api_key = 'your-api-key-here'

    def respond(self, prompt):
        "Rispondi a un prompt testuale"

        response = openai.Completion.create(
            engine="text-davinci-003",
            prompt=prompt,
            max_tokens=150
        )
        return response.choices[0].text.strip()
