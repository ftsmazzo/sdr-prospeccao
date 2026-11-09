import asyncio
import logging
import random
import re
import time

from app.checkout import create_checkout
from app.clients.elevenlabs import ElevenLabsClient
from app.clients.evolution import EvolutionClient
from app.clients.openrouter import OpenRouterClient
from app.clients.stt import SpeechToTextClient
from app.config import Settings
from app.followups import get_scheduler
from app.knowledge import load_knowledge
from app.memory import ConversationMemory
from app.messaging import split_whatsapp_messages
from app.speech import to_spoken_script

logger = logging.getLogger("edu.orchestrator")

SYSTEM_TEMPLATE = """Você é o Edu, consultor de matrícula humanizado da Faveni Polo Catanduva no WhatsApp.
Objetivo: conduzir o lead até aceitar a matrícula de pós EAD (ou 2ª licenciatura/graduação se pedir), sem alucinar e sem sair do fluxo comercial.

Regras:
- Português brasileiro, tom caloroso e profissional, mensagens curtas (WhatsApp).
- Faça UMA pergunta por vez (exceto na coleta de dados de matrícula, abaixo).
- Use SOMENTE a base de conhecimento abaixo. Não invente preço, bolsa, promoção ou telefone do polo.
- Mensalidade âncora da demo: a partir de R$ 69,90.
- Esta conversa JÁ É o atendimento; não redirecione para outro WhatsApp.
- Se o lead sair do assunto, reconheça com empatia em uma frase e volte ao funil de matrícula.
- Fluxo: qualificar → recomendar → tratar objeção → fechar.
- Evite tom de locução/institucional. Empatia calorosa, concreta e humana.
- Canal: o sistema decide texto ou áudio. Escreva a melhor mensagem; não mencione TTS.

## Fechamento — jornada (obrigatório)

Há DOIS caminhos. Nunca misture no mesmo turno.

### Caminho A — contrato primeiro (padrão se faltar documento OU lead quiser ver contrato/informativo)
1. Peça por escrito, de uma vez: nome completo, CPF e data de nascimento.
2. Explique que RG/diploma/histórico podem ser entregues DEPOIS (não bloqueiam o envio do contrato demo).
3. Quando o lead enviar os três dados, confirme em uma frase e inclua NO FINAL, sozinhas, NESTA ORDEM:
LEAD_DATA|<nome completo>|<CPF>|<data nascimento>
FOLLOWUP_DOC|<curso ou Pós-Graduação EAD Faveni>
4. Diga que você prepara o contrato/informativo (~15 min) e, se estiver ok, manda o link da matrícula em seguida.
5. NÃO use CHECKOUT_READY neste caminho. O sistema envia o link DEPOIS do PDF.
6. NÃO prometa contrato/PDF sem emitir FOLLOWUP_DOC + LEAD_DATA.

### Caminho B — checkout direto
Só se o lead já tiver dados coletados E aceitar fechar sem pedir contrato, E não houver promessa de documento pendente:
CHECKOUT_READY|<curso>
Não invente links — o sistema anexa.

Base de conhecimento:
{knowledge}
"""

# Momentos em que áudio agrega (empatia / fechamento) — não para todo turno
AUDIO_KEY_HINTS = (
    "matricul",
    "fech",
    "pagamento",
    "checkout",
    "quero sim",
    "vamos juntos",
    "aceito",
    "caro",
    "preço",
    "mensalidade",
    "medo",
    "receio",
    "não sei se",
    "inseguro",
    "obrigad",
)


class Orchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = OpenRouterClient(settings)
        self.evo = EvolutionClient(settings)
        self.stt = SpeechToTextClient(settings)
        self.tts = ElevenLabsClient(settings)
        self.memory = ConversationMemory(settings)

    def _idle_ms(self) -> int:
        lo = self.settings.human_idle_min_ms
        hi = self.settings.human_idle_max_ms
        return random.randint(lo, hi)

    def _typing_ms(self, text: str) -> int:
        approx = 1800 + int(len(text) * 35)
        lo = self.settings.typing_min_ms
        hi = self.settings.typing_max_ms
        return max(lo, min(hi, approx + random.randint(-300, 400)))

    async def _human_preamble(
        self,
        phone: str,
        *,
        remote_jid: str,
        message_id: str,
        started_at: float,
        presence: str = "composing",
        activity_ms: int = 3000,
    ) -> None:
        """Silêncio → lido → digitando/gravando (sem flicker)."""
        target_idle = self._idle_ms() / 1000.0
        elapsed = time.monotonic() - started_at
        remaining = target_idle - elapsed
        if remaining > 0.2:
            await asyncio.sleep(remaining)

        if message_id:
            await self.evo.mark_as_read(remote_jid=remote_jid or phone, message_id=message_id)

        await asyncio.sleep(random.uniform(0.4, 0.9))
        await self.evo.send_presence(phone, delay_ms=activity_ms, presence=presence)  # type: ignore[arg-type]

    def _should_reply_audio(
        self,
        *,
        phone: str,
        inbound_was_audio: bool,
        reply: str,
        course: str | None,
    ) -> bool:
        """Alterna áudio/texto: não espelha áudio em todo turno (fica seco e artificial)."""
        if not self.tts.enabled:
            return False

        meta = self.memory.get_meta(phone)
        consecutive_audio = int(meta.get("consecutive_audio_out", 0) or 0)
        low = reply.lower()
        key_moment = bool(course) or any(h in low for h in AUDIO_KEY_HINTS)

        # Evita rajada de áudios: após 1 áudio, força texto no próximo (exceto fechamento)
        if consecutive_audio >= 1 and not course:
            return False

        # Lead mandou áudio: responde áudio no máximo 1x seguidas, ou em momento-chave
        if inbound_was_audio:
            if consecutive_audio == 0:
                # 70% áudio na primeira resposta a um áudio; senão texto (variação natural)
                return random.random() < 0.7 or key_moment
            return key_moment

        # Lead mandou texto: áudio só em momento-chave (fechamento / empatia forte)
        if key_moment and consecutive_audio == 0:
            return random.random() < 0.55

        return False

    def _remember_outbound_mode(self, phone: str, *, used_audio: bool) -> None:
        meta = self.memory.get_meta(phone)
        if used_audio:
            meta["consecutive_audio_out"] = int(meta.get("consecutive_audio_out", 0) or 0) + 1
            meta["last_outbound"] = "audio"
        else:
            meta["consecutive_audio_out"] = 0
            meta["last_outbound"] = "text"
        self.memory.set_meta(phone, meta)

    async def handle_inbound(
        self,
        phone: str,
        text: str,
        *,
        push_name: str = "",
        has_audio: bool = False,
        media_message: dict | None = None,
        message_id: str = "",
        remote_jid: str = "",
    ) -> str:
        inbound_audio = bool(has_audio)
        user_text = (text or "").strip()
        started_at = time.monotonic()
        # Sem presença enquanto processa — o “digitando” só depois do lido

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
                await self._human_preamble(
                    phone,
                    remote_jid=remote_jid,
                    message_id=message_id,
                    started_at=started_at,
                    presence="composing",
                    activity_ms=2800,
                )
                await self.evo.send_text(phone, fail, delay_ms=0)
                return fail

        if not user_text:
            reply = "Não consegui entender bem — me conta em texto ou manda o áudio de novo?"
            await self._human_preamble(
                phone,
                remote_jid=remote_jid,
                message_id=message_id,
                started_at=started_at,
                presence="composing",
                activity_ms=2500,
            )
            await self.evo.send_text(phone, reply, delay_ms=0)
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
                    "content": (
                        "O lead mandou um ÁUDIO (já transcrito). Mantenha empatia e calor — "
                        "não fique seco só porque veio áudio. Continua 1 pergunta por vez."
                    ),
                }
            )
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        raw = await self.llm.chat(messages)
        reply, course, followup_course, lead_data = self._split_markers(raw)

        meta = self.memory.get_meta(phone)
        if lead_data:
            meta.update(
                {
                    "full_name": lead_data["full_name"],
                    "cpf": lead_data["cpf"],
                    "birth_date": lead_data["birth_date"],
                }
            )
            self.memory.set_meta(phone, meta)
            logger.info("LEAD_DATA salvo phone=%s", phone)

        # Caminho contrato: nunca manda link no mesmo turno
        if followup_course:
            ld = lead_data or {}
            full_name = (meta.get("full_name") or ld.get("full_name") or "").strip()
            cpf = (meta.get("cpf") or ld.get("cpf") or "").strip()
            birth = (meta.get("birth_date") or ld.get("birth_date") or "").strip()
            if not (full_name and cpf and birth):
                # Sem dados: não agenda PDF vazio — pede dados na resposta
                logger.warning("FOLLOWUP_DOC sem LEAD_DATA phone=%s — ignorado", phone)
                if "nome completo" not in reply.lower() and "cpf" not in reply.lower():
                    reply = (
                        f"{reply}\n\n"
                        "Pra eu montar o contrato certinho, me manda por escrito: "
                        "nome completo, CPF e data de nascimento. "
                        "RG e diploma podem ficar pra depois."
                    )
            else:
                get_scheduler().schedule_document(
                    phone=phone,
                    lead_name=full_name,
                    cpf=cpf,
                    birth_date=birth,
                    course=followup_course,
                    with_checkout=True,
                )
                meta["pending_contract"] = True
                meta["course"] = followup_course
                self.memory.set_meta(phone, meta)
                logger.info("FOLLOWUP_DOC agendado phone=%s course=%s", phone, followup_course)
            course = None  # bloqueia checkout imediato

        elif course:
            # Se já tem contrato pendente, não manda link agora
            if meta.get("pending_contract"):
                logger.info("CHECKOUT_READY adiado — contrato pendente phone=%s", phone)
                course = None
            else:
                name = meta.get("full_name") or push_name
                session = create_checkout(phone, course_label=course, lead_name=name or "")
                link = f"{self.settings.public_base_url.rstrip('/')}/checkout/{session.token}"
                reply = (
                    f"{reply}\n\n"
                    f"Perfeito — preparei sua matrícula (demonstração):\n{link}\n\n"
                    "É só abrir e confirmar. Documentos complementares podem ser enviados depois."
                )

        self.memory.append(phone, "user", user_text)
        self.memory.append(phone, "assistant", reply)

        want_audio = self._should_reply_audio(
            phone=phone,
            inbound_was_audio=inbound_audio,
            reply=reply,
            course=course,
        )
        if want_audio:
            try:
                spoken = await to_spoken_script(self.llm, reply)
                logger.info("tts spoken=%r", spoken[:160])
                audio = await self.tts.synthesize(spoken)
                record_ms = self._typing_ms(spoken)
                await self._human_preamble(
                    phone,
                    remote_jid=remote_jid,
                    message_id=message_id,
                    started_at=started_at,
                    presence="recording",
                    activity_ms=record_ms,
                )
                await self.evo.send_audio(phone, audio, delay_ms=0)
                self._remember_outbound_mode(phone, used_audio=True)

                if "http" in reply:
                    links = "\n".join(l for l in reply.splitlines() if "http" in l)
                    await asyncio.sleep(random.uniform(1.2, 2.0))
                    await self.evo.send_presence(phone, delay_ms=1800, presence="composing")
                    await self.evo.send_text(
                        phone,
                        "Te mando o link por escrito também:\n" + links,
                        delay_ms=0,
                    )
                return reply
            except Exception:
                logger.exception("falha TTS; caindo para texto")

        bubbles = split_whatsapp_messages(reply)
        for idx, bubble in enumerate(bubbles):
            typing_ms = self._typing_ms(bubble)
            if idx == 0:
                await self._human_preamble(
                    phone,
                    remote_jid=remote_jid,
                    message_id=message_id,
                    started_at=started_at,
                    presence="composing",
                    activity_ms=typing_ms,
                )
            else:
                await asyncio.sleep(random.uniform(1.0, 2.2))
                await self.evo.send_presence(phone, delay_ms=typing_ms, presence="composing")
            await self.evo.send_text(phone, bubble, delay_ms=0)

        self._remember_outbound_mode(phone, used_audio=False)
        return reply

    @staticmethod
    def _split_markers(
        raw: str,
    ) -> tuple[str, str | None, str | None, dict[str, str] | None]:
        text = raw.strip()
        course: str | None = None
        followup: str | None = None
        lead_data: dict[str, str] | None = None

        lead_match = re.search(r"LEAD_DATA\|(.+)$", text, flags=re.MULTILINE)
        if lead_match:
            parts = [p.strip() for p in lead_match.group(1).split("|")]
            if len(parts) >= 3:
                lead_data = {
                    "full_name": parts[0],
                    "cpf": parts[1],
                    "birth_date": parts[2],
                }
            text = re.sub(r"\n?LEAD_DATA\|.+$", "", text, flags=re.MULTILINE).strip()

        checkout_match = re.search(r"CHECKOUT_READY\|(.+)$", text, flags=re.MULTILINE)
        if checkout_match:
            course = checkout_match.group(1).strip() or "Pós-Graduação EAD Faveni"
            text = re.sub(r"\n?CHECKOUT_READY\|.+$", "", text, flags=re.MULTILINE).strip()

        followup_match = re.search(r"FOLLOWUP_DOC\|(.+)$", text, flags=re.MULTILINE)
        if followup_match:
            followup = followup_match.group(1).strip() or "Pós-Graduação EAD Faveni"
            text = re.sub(r"\n?FOLLOWUP_DOC\|.+$", "", text, flags=re.MULTILINE).strip()

        return text, course, followup, lead_data
