import asyncio
import logging
import random
import re
import time
from difflib import SequenceMatcher
from typing import Any

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
    enter_handoff,
    merge_state_update,
    reply_looks_like_callback_promise,
    reply_looks_like_delivery_promise,
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
    requests_personal_data,
    to_spoken_script,
)
from app.veracity import (
    apply_enrollment_intent,
    claims_unbacked_action,
    mark_refused_fields,
    reply_has_disallowed_price,
    reply_offers_enrollment,
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

_SCARCITY_RES = (
    re.compile(r"garantir\s+(sua|a|sua\s+própria)\s+vaga", re.IGNORECASE),
    re.compile(r"últimas?\s+vagas?", re.IGNORECASE),
    re.compile(r"ultimas?\s+vagas?", re.IGNORECASE),
    re.compile(r"só\s+hoje|so\s+hoje", re.IGNORECASE),
    re.compile(r"vagas?\s+limitadas?", re.IGNORECASE),
)

_REGEN_MOTIVOS = {
    "promessa_sem_acao": (
        "Você não pode prometer envio de contrato, PDF ou link agora "
        "(ação de entrega indisponível neste turno). "
        "Responda ao que o lead pediu sem prometer entrega futura; "
        "se ele pediu informações ou um resumo, escreva o resumo NESTA mensagem "
        "(curso, carga horária do catálogo, mensalidade da faixa em precos.md "
        "ou 'a partir de R$ 69,90' se ainda não houver curso, 100% online, "
        "troca de curso em 90 dias, documentos necessários)."
    ),
    "promessa_lembrete": (
        "Você NÃO pode prometer lembrete, retorno, 'te chamo em alguns dias' "
        "nem 'te aviso se surgir algo' — ainda não existe follow-up automático. "
        "Se o lead pediu espaço ou se despediu, diga algo como: "
        "'Quando quiser retomar, é só me chamar aqui.' Sem pergunta nova se for despedida. "
        "Não ofereça outro curso nem empurre matrícula."
    ),
    "dados_antes_fechamento": (
        "Você NÃO pode pedir nome completo, CPF ou data de nascimento agora — "
        "isso só na etapa fechamento. Responda ao pedido do lead sem coletar dados pessoais."
    ),
    "escassez": (
        "Não use urgência ou escassez inventada (ex.: garantir vaga, últimas vagas). "
        "Responda de forma informativa, sem pressionar."
    ),
    "quase_igual": (
        "Sua resposta ficou quase idêntica à anterior. Reescreva com outras palavras "
        "e avance a conversa com uma pergunta ou próximo passo diferente."
    ),
    "acao_fingida": (
        "Você afirmou uma ação que NÃO aconteceu no sistema "
        "(receber documento, confirmar com o polo, consultar, encaminhar/reforçar "
        "com especialista, já ter enviado contrato). "
        "Reescreva SEM fingir: se falar de documento, diga 'assim que chegar, eu te confirmo'; "
        "se o curso não está na lista, diga 'na nossa lista atual não tem; um especialista "
        "pode confirmar se há algo novo'; em handoff, avise UMA vez que um especialista "
        "vai dar sequência — sem repetir 'vou reforçar'."
    ),
    "preco_fora_tabela": (
        "Você citou um valor que NÃO está na tabela precos.md. "
        "Use SOMENTE mensalidade / total 18x / à vista da faixa do curso. "
        "À vista é o VALOR TOTAL da tabela — nunca divida por meses nem invente 'média mensal'. "
        "Não chame o valor à vista de 'mensalidade'."
    ),
    "matricula_sem_graduacao": (
        "Você ofereceu matrícula/passo a passo sem a graduação confirmada no estado. "
        "Pergunte primeiro se a graduação já está concluída (uma pergunta só). "
        "Não ofereça matrícula antes disso."
    ),
}


def _norm_reply(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().casefold())
    return t


def replies_nearly_equal(a: str, b: str, *, threshold: float = 0.92) -> bool:
    na, nb = _norm_reply(a), _norm_reply(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= threshold


def reply_has_scarcity(text: str) -> bool:
    return any(rx.search(text or "") for rx in _SCARCITY_RES)


class Orchestrator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.llm = OpenRouterClient(settings)
        self.evo = EvolutionClient(settings)
        self.stt = SpeechToTextClient(settings)
        self.tts = ElevenLabsClient(settings)
        self.memory = ConversationMemory(settings)
        # Diagnóstico do último _finalize_reply (sim/harness).
        self.last_reply_diag: dict[str, Any] = {}

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

    def _last_assistant_text(self, phone: str) -> str:
        history = self.memory.get_history(phone)
        for item in reversed(history):
            if item.get("role") == "assistant":
                return str(item.get("content") or "")
        return ""

    def _reply_needs_regen(
        self,
        reply: str,
        meta: dict,
        *,
        delivery_ran: bool,
        blocked_promise_reason: str | None,
        last_assistant: str,
        has_media: bool = False,
        just_entered_handoff: bool = False,
    ) -> str | None:
        if blocked_promise_reason:
            return blocked_promise_reason
        if not delivery_ran and not meta.get("pending_contract"):
            if reply_looks_like_callback_promise(reply):
                return "promessa_lembrete"
            if reply_looks_like_delivery_promise(reply):
                return "promessa_sem_acao"
        fake = claims_unbacked_action(
            reply,
            has_media=has_media,
            just_entered_handoff=just_entered_handoff,
            handoff_avisado=bool(meta.get("handoff_avisado")),
            delivery_ran=delivery_ran,
        )
        if fake:
            return "acao_fingida"
        if reply_has_disallowed_price(reply):
            return "preco_fora_tabela"
        ls = meta.get("lead_state") or {}
        if reply_offers_enrollment(reply) and not ls.get("graduacao"):
            return "matricula_sem_graduacao"
        etapa = meta.get("etapa") or ""
        if etapa != "fechamento" and requests_personal_data(reply):
            return "dados_antes_fechamento"
        if reply_has_scarcity(reply):
            return "escassez"
        if last_assistant and replies_nearly_equal(reply, last_assistant):
            return "quase_igual"
        return None

    def _regen_system_instruction(self, reason: str, meta: dict) -> str:
        base = _REGEN_MOTIVOS.get(reason) or _REGEN_MOTIVOS["promessa_sem_acao"]
        ls = meta.get("lead_state") or {}
        extra = (
            f" Etapa atual: {meta.get('etapa')}. "
            f"curso_escolhido={ls.get('curso_escolhido')!r}; "
            f"aceite_matricula={ls.get('aceite_matricula')}; "
            f"objecao_ativa={ls.get('objecao_ativa')!r}."
        )
        return (
            f"{base}{extra} "
            "Responda de novo APENAS com o JSON do schema (reply + state_update + action). "
            "Na maioria dos casos action=null. Não diga 'garantir vaga'."
        )

    async def _regenerate_reply(
        self,
        messages: list[dict],
        meta: dict,
        reason: str,
    ) -> str:
        regen_messages = list(messages) + [
            {"role": "system", "content": self._regen_system_instruction(reason, meta)}
        ]
        agent = await self._call_agent_json(regen_messages)
        # não remesclar state/actions de entrega — só o texto
        reply = (agent.reply or "").strip()
        if looks_like_json(reply):
            return ""
        return reply

    def _apply_stock_fallback(self, meta: dict, reason: str, reply: str) -> str:
        ls = meta.get("lead_state") or {}
        stock_reason = reason
        # Lembrete/retorno: stock dedicado (nunca sem_curso/sem_aceite).
        if reason == "promessa_lembrete" or (
            reason == "promessa_sem_acao" and reply_looks_like_callback_promise(reply)
        ):
            stock_reason = "promessa_lembrete"
        # promessa_sem_acao pura: stock informativo (não forçar aceite).
        # Motivos "FOLLOWUP_DOC sem_aceite" / "sem_curso" já vêm no reason e seguem.
        avoid = str(meta.get("last_stock_reply") or "")
        stock = rewrite_blocked_action_reply(stock_reason, reply, ls, avoid=avoid)
        meta["last_stock_reply"] = stock
        streak = int(meta.get("stock_streak") or 0) + 1
        meta["stock_streak"] = streak
        logger.info(
            "stock fallback reason=%s avoid_dup=%s streak=%s",
            stock_reason,
            bool(avoid),
            streak,
        )
        # Dois stocks seguidos → handoff (anti-loop).
        if streak >= 2 and meta.get("etapa") != "handoff_humano":
            enter_handoff(meta, "loop_stock")
            logger.info("handoff por loop_stock phone_meta_etapa=%s", meta.get("etapa"))
            return (
                "Vou pedir pra um especialista do polo te ajudar a seguir daqui, "
                "assim você não fica sem uma resposta clara. Em breve alguém retoma "
                "com você por aqui, tá bem?"
            )
        return stock

    def _apply_actions(
        self, phone: str, meta: dict, agent: AgentResponse, push_name: str
    ) -> tuple[str, str | None, str | None, bool]:
        """Executa action. Retorna (reply, course, blocked_promise_reason, delivery_ran)."""
        reply = agent.reply.strip()
        if looks_like_json(reply):
            reply = "Só um instante, me confirma de novo o que você precisa?"

        action = agent.action
        data = agent.action_data or {}
        ok, reason = can_run_action(meta, action)
        blocked_promise_reason: str | None = None
        if action and not ok:
            logger.info("action ignorada phone=%s reason=%s", phone, reason)
            if action in ("FOLLOWUP_DOC", "CHECKOUT_READY") and reply_looks_like_delivery_promise(
                reply
            ):
                blocked_promise_reason = reason or "promessa_sem_acao"
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

        if (
            not delivery_ran
            and not meta.get("pending_contract")
            and not blocked_promise_reason
        ):
            if reply_looks_like_callback_promise(reply):
                blocked_promise_reason = "promessa_lembrete"
            elif reply_looks_like_delivery_promise(reply):
                blocked_promise_reason = "promessa_sem_acao"

        # delivery_ran anula bloqueio de promessa (já entregou)
        if delivery_ran:
            blocked_promise_reason = None

        return reply, course, blocked_promise_reason, delivery_ran

    def _maybe_mark_handoff_avisado(
        self, meta: dict, *, just_entered_handoff: bool
    ) -> None:
        if meta.get("etapa") == "handoff_humano" and (
            just_entered_handoff or meta.get("handoff_reason")
        ):
            meta["handoff_avisado"] = True

    async def _finalize_reply(
        self,
        *,
        phone: str,
        meta: dict,
        messages: list[dict],
        reply: str,
        course: str | None,
        blocked_promise_reason: str | None,
        delivery_ran: bool,
        has_media: bool = False,
        just_entered_handoff: bool = False,
    ) -> str:
        self.last_reply_diag = {
            "regen": False,
            "regen_reason": None,
            "stock": False,
            "stock_reason": None,
            "stock_text": None,
        }
        last_assistant = self._last_assistant_text(phone)
        reason = self._reply_needs_regen(
            reply,
            meta,
            delivery_ran=delivery_ran,
            blocked_promise_reason=blocked_promise_reason,
            last_assistant=last_assistant,
            has_media=has_media,
            just_entered_handoff=just_entered_handoff,
        )
        if reason:
            self.last_reply_diag["regen"] = True
            self.last_reply_diag["regen_reason"] = reason
            logger.info("regen reply reason=%s", reason)
            regenerated = await self._regenerate_reply(messages, meta, reason)
            if regenerated:
                still_blocked = None
                if reply_looks_like_callback_promise(regenerated):
                    still_blocked = "promessa_lembrete"
                elif reply_looks_like_delivery_promise(regenerated):
                    still_blocked = "promessa_sem_acao"
                still = self._reply_needs_regen(
                    regenerated,
                    meta,
                    delivery_ran=delivery_ran
                    if reason not in ("promessa_sem_acao", "promessa_lembrete")
                    else False,
                    blocked_promise_reason=still_blocked,
                    last_assistant=last_assistant,
                    has_media=has_media,
                    just_entered_handoff=just_entered_handoff,
                )
                if not still:
                    meta["stock_streak"] = 0
                    self._maybe_mark_handoff_avisado(
                        meta, just_entered_handoff=just_entered_handoff
                    )
                    return regenerated
                logger.info("regen ainda viola (%s) — stock", still)
                stock = self._apply_stock_fallback(meta, still or reason, regenerated)
                self.last_reply_diag["stock"] = True
                self.last_reply_diag["stock_reason"] = still or reason
                self.last_reply_diag["stock_text"] = stock
                if meta.get("handoff_reason") == "loop_stock":
                    self.last_reply_diag["stock_reason"] = "loop_stock"
                self._maybe_mark_handoff_avisado(
                    meta, just_entered_handoff=just_entered_handoff
                )
                return stock
            stock = self._apply_stock_fallback(meta, reason, reply)
            self.last_reply_diag["stock"] = True
            self.last_reply_diag["stock_reason"] = (
                "loop_stock" if meta.get("handoff_reason") == "loop_stock" else reason
            )
            self.last_reply_diag["stock_text"] = stock
            self._maybe_mark_handoff_avisado(
                meta, just_entered_handoff=just_entered_handoff
            )
            return stock
        meta["stock_streak"] = 0
        self._maybe_mark_handoff_avisado(
            meta, just_entered_handoff=just_entered_handoff
        )
        return reply

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

        last_assistant = self._last_assistant_text(phone)
        mark_refused_fields(meta, lead_text=user_text, last_agent=last_assistant)
        ls = meta.get("lead_state") or ls

        etapa_antes = meta.get("etapa") or "abertura"
        system = build_system_prompt(
            etapa=etapa_antes,
            lead_state=ls,
            meta_flags={
                "pending_contract": meta.get("pending_contract"),
                "contract_sent": meta.get("contract_sent"),
                "desconto_respondido": meta.get("desconto_respondido"),
                "handoff_reason": meta.get("handoff_reason"),
                "handoff_avisado": meta.get("handoff_avisado"),
                "campos_recusados": meta.get("campos_recusados") or [],
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
        has_media = bool(has_image or has_document)
        if has_media:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "O lead enviou imagem/documento NESTE turno. "
                        "Só agora você pode confirmar o recebimento."
                    ),
                }
            )
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})

        agent = await self._call_agent_json(messages)

        # merge fatos (sem etapa); capturar flags de turno antes do advance zerar
        lead_irritado_turn = bool(agent.state_update.get("lead_irritado"))
        merge_state_update(ls, agent.state_update)
        apply_enrollment_intent(ls, user_text)
        meta["lead_state"] = ls
        advance_etapa(meta, handoff_max_objecoes=self.settings.handoff_max_objecoes)
        just_entered_handoff = (
            meta.get("etapa") == "handoff_humano" and etapa_antes != "handoff_humano"
        )
        if meta.get("etapa") == "handoff_humano":
            logger.info("handoff_humano phone=%s summary=%s", phone, summarize_lead(meta))

        reply, course, blocked_promise_reason, delivery_ran = self._apply_actions(
            phone, meta, agent, push_name
        )
        reply = await self._finalize_reply(
            phone=phone,
            meta=meta,
            messages=messages,
            reply=reply,
            course=course,
            blocked_promise_reason=blocked_promise_reason,
            delivery_ran=delivery_ran,
            has_media=has_media,
            just_entered_handoff=just_entered_handoff,
        )
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
