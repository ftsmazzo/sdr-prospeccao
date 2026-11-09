import asyncio
import logging
import random
import time

from app.audio_post import to_whatsapp_voice
from app.checkout import create_checkout
from app.clients.elevenlabs import ElevenLabsClient
from app.clients.evolution import EvolutionClient
from app.clients.openrouter import OpenRouterClient
from app.clients.stt import SpeechToTextClient
from app.config import Settings
from app.followups import get_scheduler
from app.lead_state import (
    advance_etapa,
    can_run_action,
    ensure_lead_state,
    merge_state_update,
    reply_looks_like_promise,
    rewrite_blocked_action_reply,
    summarize_lead,
)
from app.memory import ConversationMemory
from app.messaging import split_whatsapp_messages
from app.prompt_builder import build_system_prompt
from app.schemas import (
    AgentResponse,
    looks_like_json,
    normalize_cpf,
    parse_agent_response,
    safe_fallback_response,
)
from app.speech import (
    asks_or_confirms_personal_data,
    contains_link,
    extract_audio_opening,
    to_spoken_script,
)

logger = logging.getLogger("edu.orchestrator")

AUDIO_KEY_HINTS = (
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
        return random.randint(self.settings.human_idle_min_ms, self.settings.human_idle_max_ms)

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
        if not self.tts.enabled:
            return False
        if asks_or_confirms_personal_data(reply) or contains_link(reply):
            return False
        meta = self.memory.get_meta(phone)
        consecutive_audio = int(meta.get("consecutive_audio_out", 0) or 0)
        low = reply.lower()
        key_moment = bool(course) or any(h in low for h in AUDIO_KEY_HINTS)
        if consecutive_audio >= 1 and not course:
            return False
        if inbound_was_audio:
            if consecutive_audio == 0:
                return random.random() < 0.7 or key_moment
            return key_moment
        if key_moment and consecutive_audio == 0:
            return random.random() < 0.55
        return False

    def _allow_expression_tags(self, meta: dict, reply: str, lead_irritado_turn: bool) -> bool:
        etapa = meta.get("etapa") or ""
        if etapa in ("handoff_humano", "aluno_atual"):
            return False
        if lead_irritado_turn:
            return False
        return not asks_or_confirms_personal_data(reply)

    def _remember_outbound_mode(self, phone: str, *, used_audio: bool) -> None:
        meta = self.memory.get_meta(phone)
        if used_audio:
            meta["consecutive_audio_out"] = int(meta.get("consecutive_audio_out", 0) or 0) + 1
            meta["last_outbound"] = "audio"
        else:
            meta["consecutive_audio_out"] = 0
            meta["last_outbound"] = "text"
        self.memory.set_meta(phone, meta)

    async def merge_inbound_batch(self, batch: list[dict]) -> dict:
        parts: list[str] = []
        push_name = ""
        remote_jid = ""
        message_id = ""
        has_audio = False
        has_image = False
        has_document = False
        doc_names: list[str] = []

        for item in batch:
            push_name = item.get("push_name") or push_name
            if item.get("remote_jid"):
                remote_jid = item["remote_jid"]
            if item.get("message_id"):
                message_id = item["message_id"]
            if item.get("has_image"):
                has_image = True
            if item.get("has_document"):
                has_document = True
                fn = (item.get("document_filename") or "").strip()
                if fn:
                    doc_names.append(fn)

            text_bit = (item.get("text") or "").strip()
            if item.get("has_audio") and item.get("media_message"):
                has_audio = True
                try:
                    audio_bytes = await self.evo.download_media(item["media_message"])
                    transcript = (await self.stt.transcribe(audio_bytes)).strip()
                    logger.info("áudio transcrito phone=%s text=%r", item.get("phone"), transcript[:120])
                    if transcript:
                        parts.append(transcript)
                    elif text_bit:
                        parts.append(text_bit)
                except Exception:
                    logger.exception("falha STT no lote")
                    parts.append("[áudio não transcrito]")
            elif text_bit:
                parts.append(text_bit)

        return {
            "text": "\n".join(parts).strip(),
            "push_name": push_name,
            "remote_jid": remote_jid,
            "message_id": message_id,
            "has_audio": has_audio,
            "has_image": has_image,
            "has_document": has_document,
            "document_filename": ", ".join(doc_names),
        }

    async def _call_agent_json(self, messages: list[dict]) -> AgentResponse:
        raw = await self.llm.chat(messages, temperature=0.4)
        parsed = parse_agent_response(raw)
        if parsed:
            return parsed

        logger.warning("JSON inválido — retry")
        retry_messages = list(messages) + [
            {
                "role": "system",
                "content": (
                    "Sua resposta anterior não era JSON válido. "
                    "Responda SOMENTE o objeto JSON do schema, sem markdown."
                ),
            }
        ]
        raw2 = await self.llm.chat(retry_messages, temperature=0.2)
        parsed2 = parse_agent_response(raw2)
        if parsed2:
            return parsed2
        return safe_fallback_response(raw2 or raw)

    def _apply_actions(self, phone: str, meta: dict, agent: AgentResponse, push_name: str) -> tuple[str, str | None]:
        """Executa action permitida. Retorna (reply, course_for_audio)."""
        reply = agent.reply.strip()
        if looks_like_json(reply):
            reply = "Só um instante, me confirma de novo o que você precisa?"

        action = agent.action
        data = agent.action_data or {}
        ok, reason = can_run_action(meta, action)
        blocked_delivery = False
        blocked_reason = reason
        if action and not ok:
            logger.info("action ignorada phone=%s reason=%s", phone, reason)
            if action in ("FOLLOWUP_DOC", "CHECKOUT_READY") and reply_looks_like_promise(reply):
                blocked_delivery = True
            action = None

        course: str | None = None
        ls = meta["lead_state"]
        delivery_ran = False

        if action == "LEAD_DATA":
            full_name = str(data.get("full_name") or "").strip()
            cpf = normalize_cpf(str(data.get("cpf") or ""))
            birth = str(data.get("birth_date") or "").strip()
            if full_name and cpf and birth:
                meta["full_name"] = full_name
                meta["cpf"] = cpf
                meta["birth_date"] = birth
                ls["nome"] = full_name
            else:
                logger.warning("LEAD_DATA incompleto/CPF inválido phone=%s", phone)

        elif action == "FOLLOWUP_DOC":
            course = str(ls.get("curso_escolhido") or data.get("course") or "Pós-Graduação EAD Faveni").strip()
            full_name = str(data.get("full_name") or meta.get("full_name") or ls.get("nome") or "").strip()
            cpf = normalize_cpf(str(data.get("cpf") or meta.get("cpf") or ""))
            birth = str(data.get("birth_date") or meta.get("birth_date") or "").strip()
            if not (full_name and cpf and birth):
                logger.warning("FOLLOWUP_DOC sem dados phone=%s", phone)
                if "cpf" not in reply.lower() and "nome completo" not in reply.lower():
                    reply = (
                        f"{reply}\n\n"
                        "Pra adiantar o contrato, me manda por escrito: "
                        "nome completo, CPF e data de nascimento. "
                        "Depois que fecharmos, você envia a documentação "
                        "(RG ou CNH, diploma ou declaração, histórico e certidão)."
                    )
            else:
                meta["full_name"] = full_name
                meta["cpf"] = cpf
                meta["birth_date"] = birth
                ls["nome"] = full_name
                ls["curso_escolhido"] = course
                get_scheduler().schedule_document(
                    phone=phone,
                    lead_name=full_name,
                    cpf=cpf,
                    birth_date=birth,
                    course=course,
                    with_checkout=True,
                )
                meta["pending_contract"] = True
                meta["course"] = course
                delivery_ran = True
                logger.info("FOLLOWUP_DOC agendado phone=%s course=%s", phone, course)

        elif action == "CHECKOUT_READY":
            course = str(ls.get("curso_escolhido") or data.get("course") or "Pós-Graduação EAD Faveni").strip()
            name = meta.get("full_name") or ls.get("nome") or push_name
            session = create_checkout(phone, course_label=course, lead_name=name or "")
            link = f"{self.settings.public_base_url.rstrip('/')}/checkout/{session.token}"
            reply = (
                f"{reply}\n\n"
                f"Perfeito — preparei sua matrícula (demonstração):\n{link}\n\n"
                "É só abrir e confirmar. Documentos complementares podem ser enviados depois."
            )
            delivery_ran = True

        if blocked_delivery:
            reply = rewrite_blocked_action_reply(blocked_reason, reply, ls)
            logger.info("promessa reescrita phone=%s reason=%s", phone, blocked_reason)
        elif (
            not delivery_ran
            and not meta.get("pending_contract")
            and reply_looks_like_promise(reply)
        ):
            reply = rewrite_blocked_action_reply("promessa_sem_acao", reply, ls)
            logger.info("promessa_sem_acao phone=%s", phone)

        return reply, course
    async def handle_inbound(
        self,
        phone: str,
        text: str,
        *,
        push_name: str = "",
        has_audio: bool = False,
        has_image: bool = False,
        has_document: bool = False,
        document_filename: str = "",
        media_message: dict | None = None,
        message_id: str = "",
        remote_jid: str = "",
    ) -> str:
        inbound_audio = bool(has_audio)
        user_text = (text or "").strip()
        started_at = time.monotonic()

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

        if not user_text and (has_image or has_document):
            kind = "documento" if has_document else "foto"
            extra = f" ({document_filename})" if document_filename else ""
            user_text = (
                f"[Lead enviou {kind}{extra} sem texto. "
                "Confirme o recebimento e continue o funil de matrícula.]"
            )

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

        meta = self.memory.get_meta(phone)
        ls = ensure_lead_state(meta)
        if push_name and not ls.get("nome"):
            # não assume nome legal; só contexto
            pass

        etapa = meta.get("etapa") or "abertura"
        system = build_system_prompt(
            etapa=etapa,
            lead_state=ls,
            meta_flags={
                "pending_contract": meta.get("pending_contract"),
                "contract_sent": meta.get("contract_sent"),
                "desconto_respondido": meta.get("desconto_respondido"),
                "handoff_reason": meta.get("handoff_reason"),
            },
            agent_name=self.settings.agent_name,
            agent_gender=self.settings.agent_gender,
        )
        history = self.memory.get_history(phone)
        messages: list[dict] = [{"role": "system", "content": system}]
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
                    "content": "O lead mandou ÁUDIO (já transcrito). Mantenha empatia e calor.",
                }
            )
        if has_image or has_document:
            messages.append(
                {
                    "role": "system",
                    "content": "O lead enviou imagem/documento. Confirme o recebimento e siga o funil.",
                }
            )
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        agent = await self._call_agent_json(messages)

        # merge fatos (sem etapa); capturar flags de turno antes do advance zerar
        lead_irritado_turn = bool(agent.state_update.get("lead_irritado"))
        merge_state_update(ls, agent.state_update)
        meta["lead_state"] = ls
        advance_etapa(meta, handoff_max_objecoes=self.settings.handoff_max_objecoes)
        if meta.get("etapa") == "handoff_humano":
            logger.info("handoff_humano phone=%s summary=%s", phone, summarize_lead(meta))

        reply, course = self._apply_actions(phone, meta, agent, push_name)
        self.memory.set_meta(phone, meta)

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
                allow_tags = self._allow_expression_tags(meta, reply, lead_irritado_turn)
                spoken = await to_spoken_script(
                    self.llm,
                    reply,
                    agent_name=self.settings.agent_name,
                    agent_gender=self.settings.agent_gender,
                    allow_expression_tags=allow_tags,
                    last_audio_opening=str(meta.get("last_audio_opening") or ""),
                )
                logger.info("tts spoken=%r allow_tags=%s", spoken[:160], allow_tags)
                mp3 = await self.tts.synthesize(spoken)
                audio, fmt = to_whatsapp_voice(mp3)
                # OGG já é nota de voz → encoding do env; MP3 fallback força re-encode PTT
                encoding = True if fmt == "mp3" else self.settings.evolution_audio_encoding
                record_ms = self._typing_ms(spoken)
                await self._human_preamble(
                    phone,
                    remote_jid=remote_jid,
                    message_id=message_id,
                    started_at=started_at,
                    presence="recording",
                    activity_ms=record_ms,
                )
                await self.evo.send_audio(phone, audio, delay_ms=0, encoding=encoding)
                meta["last_audio_opening"] = extract_audio_opening(spoken)
                self.memory.set_meta(phone, meta)
                self._remember_outbound_mode(phone, used_audio=True)
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
