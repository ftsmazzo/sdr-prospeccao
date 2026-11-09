import logging
import random
import re

from app.checkout import create_checkout
from app.clients.elevenlabs import ElevenLabsClient
from app.clients.evolution import EvolutionClient
from app.clients.openrouter import OpenRouterClient
from app.clients.stt import SpeechToTextClient
from app.config import Settings
from app.knowledge import load_knowledge
from app.memory import ConversationMemory
from app.speech import to_spoken_script

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
- Se o lead mandou áudio, responda de forma natural (como em conversa falada), ainda com 1 pergunta por vez.
- Evite tom de locução/institucional (“é uma escolha muito importante…”). Empatia curta e concreta.

Base de conhecimento:
{knowledge}
"""

KEY_MOMENT_HINTS = (
    "matricul",
    "fech",
    "pagamento",
    "checkout",
    "quero sim",
    "vamos",
    "pode ser",
    "aceito",
    "tea",
    "objeção",
    "caro",
    "preço",
    "mensalidade",
)


class Orchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = OpenRouterClient(settings)
        self.evo = EvolutionClient(settings)
        self.stt = SpeechToTextClient(settings)
        self.tts = ElevenLabsClient(settings)
        self.memory = ConversationMemory(settings)

    def _human_delay_ms(self, text: str) -> int:
        # ~35–45ms por caractere, com piso/teto humanizados
        approx = 2800 + int(len(text) * 40)
        lo = self.settings.reply_delay_min_ms
        hi = self.settings.reply_delay_max_ms
        return max(lo, min(hi, approx + random.randint(-400, 600)))

    def _should_reply_audio(self, *, inbound_was_audio: bool, reply: str, course: str | None) -> bool:
        if not self.tts.enabled:
            return False
        if inbound_was_audio:
            return True
        if course:
            return True
        low = reply.lower()
        return any(h in low for h in KEY_MOMENT_HINTS)

    async def handle_inbound(
        self,
        phone: str,
        text: str,
        *,
        push_name: str = "",
        has_audio: bool = False,
        media_message: dict | None = None,
    ) -> str:
        inbound_audio = bool(has_audio)
        user_text = (text or "").strip()

        # Digitando cedo, enquanto processamos STT/LLM
        await self.evo.send_presence(phone, delay_ms=5000)

        if inbound_audio and not user_text and media_message:
            try:
                audio_bytes = await self.evo.download_media(media_message)
                user_text = await self.stt.transcribe(audio_bytes)
                logger.info("áudio transcrito phone=%s text=%r", phone, user_text[:120])
            except Exception:
                logger.exception("falha STT")
                nome = (push_name or "").split()[0] or "aí"
                fail = (
                    f"Recebi seu áudio, {nome} — tô com um probleminha pra ouvir agora. "
                    "Pode me mandar em texto rapidinho o que você busca?"
                )
                await self.evo.send_text(phone, fail, delay_ms=3500)
                return fail

        if not user_text:
            reply = "Não consegui entender bem — me conta em texto ou manda o áudio de novo?"
            await self.evo.send_text(phone, reply, delay_ms=3500)
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
        if inbound_audio:
            messages.append(
                {
                    "role": "system",
                    "content": "O lead acabou de mandar um ÁUDIO (já transcrito). Responda de forma falada/natural.",
                }
            )
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

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

        self.memory.append(phone, "user", user_text)
        self.memory.append(phone, "assistant", reply)

        delay = self._human_delay_ms(reply)
        await self.evo.send_presence(phone, delay_ms=delay)

        want_audio = self._should_reply_audio(
            inbound_was_audio=inbound_audio, reply=reply, course=course
        )
        if want_audio:
            try:
                # TTS usa roteiro FALADO (não o texto escrito do chat)
                spoken = await to_spoken_script(self.llm, reply)
                logger.info("tts spoken=%r", spoken[:160])
                audio = await self.tts.synthesize(spoken)
                await self.evo.send_audio(phone, audio, delay_ms=1600)
                if course or "http" in reply:
                    # garante o link clicável em texto
                    link_only = "\n".join(
                        line for line in reply.splitlines() if "http" in line or "checkout" in line.lower()
                    )
                    if not link_only and course:
                        link_only = reply
                    if "http" in reply:
                        await self.evo.send_text(
                            phone,
                            "Te mandei também o link por escrito pra ficar fácil de abrir:\n"
                            + "\n".join(l for l in reply.splitlines() if l.startswith("http") or "http" in l),
                            delay_ms=2200,
                        )
                return reply
            except Exception:
                logger.exception("falha TTS; caindo para texto")

        await self.evo.send_text(phone, reply, delay_ms=delay)
        return reply

    @staticmethod
    def _split_checkout(raw: str) -> tuple[str, str | None]:
        match = re.search(r"CHECKOUT_READY\|(.+)$", raw.strip(), flags=re.MULTILINE)
        if not match:
            return raw.strip(), None
        course = match.group(1).strip() or "Pós-Graduação EAD Faveni"
        cleaned = re.sub(r"\n?CHECKOUT_READY\|.+$", "", raw.strip(), flags=re.MULTILINE).strip()
        return cleaned, course
