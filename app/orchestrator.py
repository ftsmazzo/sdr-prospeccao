import logging
import re

from app.checkout import create_checkout
from app.clients.evolution import EvolutionClient
from app.clients.openrouter import OpenRouterClient
from app.config import Settings
from app.knowledge import load_knowledge
from app.memory import ConversationMemory

logger = logging.getLogger("edu.orchestrator")

SYSTEM_TEMPLATE = """Você é o Edu, consultor de matrícula humanizado da Faveni Polo Catanduva no WhatsApp.
Objetivo: conduzir o lead até aceitar a matrícula de pós EAD (ou 2ª licenciatura/graduação se pedir), sem alucinar e sem sair do fluxo comercial.

Regras:
- Português brasileiro, tom caloroso e profissional, mensagens curtas (WhatsApp).
- Faça UMA pergunta por vez.
- Use SOMENTE a base de conhecimento abaixo. Não invente preço, bolsa, promoção ou telefone do polo.
- Mensalidade âncora da demo: a partir de R$ 69,90.
- Esta conversa JÁ É o atendimento; não redirecione para outro WhatsApp.
- Se o lead sair do assunto, reconheça com empatia em uma frase e volte ao funil de matrícula.
- Fluxo: qualificar → recomendar → tratar objeção → fechar.
- Quando o lead aceitar matricular / quiser fechar / pedir pagamento, responda confirmando e inclua EXATAMENTE esta linha sozinha no final:
CHECKOUT_READY|<curso escolhido ou Pós-Graduação EAD Faveni>
- Não invente links. O sistema anexa o link de checkout depois.

Base de conhecimento:
{knowledge}
"""


class Orchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = OpenRouterClient(settings)
        self.evo = EvolutionClient(settings)
        self.memory = ConversationMemory(settings)

    async def handle_inbound(self, phone: str, text: str, push_name: str = "") -> str:
        if not text.strip():
            reply = (
                "Recebi seu áudio! Por enquanto nesta demo consigo responder melhor por texto — "
                "me conta em poucas palavras o que você busca: pós, 2ª licenciatura ou graduação?"
            )
            await self.evo.send_text(phone, reply)
            return reply

        knowledge = load_knowledge()
        system = SYSTEM_TEMPLATE.format(knowledge=knowledge[:12000])
        history = self.memory.get_history(phone)
        messages = [{"role": "system", "content": system}]
        if push_name and not history:
            messages.append(
                {
                    "role": "system",
                    "content": f"O lead se apresenta no WhatsApp como: {push_name}. Use o primeiro nome com naturalidade.",
                }
            )
        messages.extend(history)
        messages.append({"role": "user", "content": text})

        raw = await self.llm.chat(messages)
        reply, course = self._split_checkout(raw)
        if course:
            session = create_checkout(phone, course_label=course, lead_name=push_name)
            link = f"{self.settings.public_base_url.rstrip('/')}/checkout/{session.token}"
            reply = (
                f"{reply}\n\n"
                f"Perfeito — preparei sua matrícula (demonstração):\n{link}\n\n"
                "É só abrir e confirmar o pagamento simulado. Qualquer dúvida, estou aqui."
            )

        self.memory.append(phone, "user", text)
        self.memory.append(phone, "assistant", reply)
        await self.evo.send_text(phone, reply)
        return reply

    @staticmethod
    def _split_checkout(raw: str) -> tuple[str, str | None]:
        match = re.search(r"CHECKOUT_READY\|(.+)$", raw.strip(), flags=re.MULTILINE)
        if not match:
            return raw.strip(), None
        course = match.group(1).strip() or "Pós-Graduação EAD Faveni"
        cleaned = re.sub(r"\n?CHECKOUT_READY\|.+$", "", raw.strip(), flags=re.MULTILINE).strip()
        return cleaned, course
