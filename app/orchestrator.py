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
    begin_new_purchase,
    can_run_action,
    ensure_lead_state,
    enter_handoff,
    lead_asks_explicit_callback,
    lead_says_farewell_or_space,
    lead_soft_deferral,
    reply_looks_lazy_close,
    soft_deferral_probe_reply,
    merge_state_update,
    reply_looks_like_callback_promise,
    reply_looks_like_delivery_promise,
    rewrite_blocked_action_reply,
    summarize_lead,
)
from app.memory import ConversationMemory
from app.messaging import split_whatsapp_messages
from app.prompt_builder import (
    build_cached_system_message,
    build_system_prompt_parts,
)
from app.schemas import (
    RESPONDER_TOOL,
    RESPONDER_TOOL_CHOICE,
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
from app.course_facts import (
    facts_for_lead_state,
    format_facts_block,
    reply_has_wrong_course_facts,
    resolve_catalog_name,
)
from app.handoff_requests import (
    can_execute_register_handoff,
    handoff_registered_reply,
    lead_accepts_specialist,
    lead_refuses_handoff,
    register_handoff_request,
)
from app.briefing import refresh_briefing
from app.compra_atual import (
    ensure_compra_atual,
    sync_ls_into_compra_atual,
)
from app.contract_party import resolve_contract_party
from app.lead_data import (
    apply_extracted_contract_fields,
    extract_contract_fields_from_text,
)
from app.notify import (
    build_handoff_notify_message,
    is_internal_number,
    notify_numbers,
    parse_notify_numbers,
)
from app.offers import (
    apply_third_person_flags,
    classify_offer_response_fallback,
    contract_data_request_reply,
    detect_third_person_student,
    infer_offer_from_reply,
    lead_affirms_offer,
    lead_asks_if_registered,
    lead_refuses_offer,
    lead_wants_new_purchase,
    missing_contract_fields,
    normalize_offer,
)
from app.veracity import (
    apply_enrollment_intent,
    claims_unbacked_action,
    lead_says_sending_document,
    mark_refused_fields,
    reply_has_disallowed_price,
    reply_has_invented_policy,
    reply_has_markdown_list,
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
    re.compile(
        r"\b(?:garantir|garante|garanta)\s+(?:sua\s+)?(?:a\s+)?vaga\b",
        re.IGNORECASE,
    ),
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
        "isso só na etapa fechamento. Responda DIRETO à última mensagem do lead "
        "(interesse, curso, dúvida) com uma pergunta neutra ligada ao que ele disse. "
        "NUNCA use despedida ('Quando quiser retomar…') neste caso."
    ),
    "promessa_lembrete_nao_despedida": (
        "O lead NÃO se despediu. Responda DIRETO à última mensagem dele com "
        "uma pergunta neutra ligada ao que ele pediu. "
        "NUNCA diga 'Quando quiser retomar, é só me chamar aqui'."
    ),
    "escassez": (
        "Não use urgência ou escassez inventada (ex.: garantir vaga, últimas vagas). "
        "Responda de forma informativa, sem pressionar."
    ),
    "quase_igual": (
        "Sua resposta ficou quase idêntica a uma das últimas 3. Reescreva com outras "
        "palavras e avance com uma pergunta ou próximo passo diferente. "
        "Não repita o mesmo resumo."
    ),
    "politica_inventada": (
        "Você inventou política fora da base (ex.: 'não enviamos contrato no WhatsApp', "
        "'contrato vai por e-mail', prazo inventado). Reescreva: o PDF do contrato "
        "é enviado por WhatsApp após os dados; use só fatos da base."
    ),
    "acao_fingida": (
        "Você afirmou uma ação que NÃO aconteceu no sistema "
        "(receber documento, confirmar/verificar com o polo, acionar especialista, "
        "aguardar retorno, já ter enviado contrato, 'assim que o documento chegar' "
        "sem o lead ter dito que vai enviar). "
        "Reescreva SEM fingir e SEM meta-fala (não diga catálogo/tabela/regras). "
        "Se o sistema registrou handoff NESTE turno, diga: "
        "'Registrei seu pedido; um especialista do polo vai falar com você por aqui.' "
        "Se perguntarem andamento depois: 'seu pedido está registrado; o especialista "
        "te chama por aqui.' Nunca diga que verificou ou recebeu retorno."
    ),
    "preco_fora_tabela": (
        "Você citou um valor fora da faixa do curso. "
        "Use SOMENTE mensalidade / total 18x / à vista corretos. "
        "À vista é o VALOR TOTAL — nunca divida por meses nem invente 'média mensal'. "
        "Não chame o valor à vista de 'mensalidade'. Fale os números direto, "
        "sem mencionar tabela/catálogo."
    ),
    "matricula_sem_graduacao": (
        "Você ofereceu matrícula/passo a passo sem a graduação confirmada no estado. "
        "Pergunte primeiro se a graduação já está concluída (uma pergunta só). "
        "Não ofereça matrícula antes disso."
    ),
    "fato_curso_errado": (
        "Você citou carga horária, duração mínima ou preço diferente dos "
        "'Fatos dos cursos em discussão'. Reescreva usando EXATAMENTE esses números, "
        "em tom humano, sem mencionar catálogo, tabela, dados oficiais ou regras. "
        "Se o lead corrigiu e ele estava certo, agradeça e corrija."
    ),
    "lista_markdown": (
        "Não use listas com marcadores (-, *, 1.) no WhatsApp. "
        "Reescreva em texto corrido, no máximo 2–3 frases."
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
        raw = await self.llm.chat_tool(
            messages,
            tools=[RESPONDER_TOOL],
            tool_choice=RESPONDER_TOOL_CHOICE,
            temperature=0.4,
        )
        parsed = parse_agent_response(raw)
        if parsed:
            return parsed

        logger.warning("JSON/tool inválido — retry bruto=%r", (raw or "")[:400])
        retry_messages = list(messages) + [
            {
                "role": "system",
                "content": (
                    "A chamada anterior à ferramenta `responder` falhou ou veio inválida. "
                    "Chame `responder` de novo com JSON válido "
                    "(reply, state_update, action, action_data, offer)."
                ),
            }
        ]
        raw2 = await self.llm.chat_tool(
            retry_messages,
            tools=[RESPONDER_TOOL],
            tool_choice=RESPONDER_TOOL_CHOICE,
            temperature=0.2,
        )
        parsed2 = parse_agent_response(raw2)
        if parsed2:
            return parsed2
        return safe_fallback_response(raw2 or raw)

    def _last_assistant_text(self, phone: str) -> str:
        recent = self._recent_assistant_texts(phone, n=1)
        return recent[0] if recent else ""

    def _recent_assistant_texts(self, phone: str, n: int = 3) -> list[str]:
        history = self.memory.get_history(phone)
        out: list[str] = []
        for item in reversed(history):
            if item.get("role") == "assistant":
                content = str(item.get("content") or "").strip()
                if content:
                    out.append(content)
                if len(out) >= n:
                    break
        return out

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
        user_text: str = "",
        recent_assistants: list[str] | None = None,
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
            handoff_registered_this_turn=bool(meta.get("_handoff_registered_this_turn")),
            handoff_registrado=bool(meta.get("handoff_registrado")),
            lead_sending_document=lead_says_sending_document(user_text),
        )
        if fake:
            return "acao_fingida"
        if reply_has_invented_policy(reply):
            return "politica_inventada"
        if reply_has_disallowed_price(reply):
            return "preco_fora_tabela"
        if reply_has_wrong_course_facts(reply):
            return "fato_curso_errado"
        if reply_has_markdown_list(reply):
            return "lista_markdown"
        ls = meta.get("lead_state") or {}
        if reply_offers_enrollment(reply) and not ls.get("graduacao"):
            return "matricula_sem_graduacao"
        etapa = meta.get("etapa") or ""
        if etapa != "fechamento" and requests_personal_data(reply):
            return "dados_antes_fechamento"
        if reply_has_scarcity(reply):
            return "escassez"
        priors = recent_assistants if recent_assistants is not None else (
            [last_assistant] if last_assistant else []
        )
        for prior in priors:
            if prior and replies_nearly_equal(reply, prior):
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

    def _apply_stock_fallback(
        self, meta: dict, reason: str, reply: str, *, user_text: str = ""
    ) -> str:
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
        stock = rewrite_blocked_action_reply(
            stock_reason, reply, ls, avoid=avoid, user_text=user_text
        )
        # Nunca enviar despedida se o lead não se despediu.
        if (
            not lead_says_farewell_or_space(user_text)
            and "quando quiser retomar" in stock.casefold()
        ):
            stock = (
                "Me conta o que você precisa saber agora que eu te respondo por aqui?"
            )
        meta["last_stock_reply"] = stock
        streak = int(meta.get("stock_streak") or 0) + 1
        meta["stock_streak"] = streak
        logger.info(
            "stock fallback reason=%s avoid_dup=%s streak=%s",
            stock_reason,
            bool(avoid),
            streak,
        )
        # Dois stocks seguidos → handoff (anti-loop), sem auto-registro Redis.
        if streak >= 2 and meta.get("etapa") != "handoff_humano":
            enter_handoff(meta, "loop_stock")
            logger.info("handoff por loop_stock phone_meta_etapa=%s", meta.get("etapa"))
            return (
                "Quando quiser, um especialista do polo pode te ajudar por aqui. "
                "Quer que eu registre seu pedido?"
            )
        return stock

    def _apply_actions(
        self,
        phone: str,
        meta: dict,
        agent: AgentResponse,
        push_name: str,
        *,
        user_text: str = "",
        last_assistant: str = "",
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

        if action == "REGISTER_HANDOFF":
            gate_ok, gate_reason = can_execute_register_handoff(
                last_assistant=last_assistant,
                user_text=user_text,
                already_registered=bool(meta.get("handoff_registrado")),
            )
            if not gate_ok:
                logger.info(
                    "REGISTER_HANDOFF ignorada phone=%s reason=%s",
                    phone,
                    gate_reason,
                )
                action = None
            else:
                motivo = str(
                    data.get("motivo")
                    or meta.get("handoff_reason")
                    or ls.get("area_interesse")
                    or "especialista"
                )
                # Dúvida pontual: registra em paralelo SEM mudar a etapa do funil.
                # handoff_humano fica só para advance_etapa (desconto, jurídico, irritado…).
                self._register_handoff_now(
                    phone=phone,
                    meta=meta,
                    motivo=motivo,
                    push_name=push_name,
                )
                meta["handoff_avisado"] = True
                if not re.search(r"(?i)\bregistrei\b", reply or ""):
                    reply = handoff_registered_reply(
                        nome=ls.get("nome") or push_name or None,
                        motivo=motivo,
                    )
                logger.info(
                    "REGISTER_HANDOFF ok phone=%s motivo=%s etapa=%s",
                    phone,
                    motivo,
                    meta.get("etapa"),
                )

        elif action == "LEAD_DATA":
            full_name = str(data.get("full_name") or "").strip()
            cpf = normalize_cpf(str(data.get("cpf") or ""))
            birth = str(data.get("birth_date") or "").strip()
            if full_name and cpf and birth:
                from app.lead_data import apply_extracted_contract_fields

                apply_extracted_contract_fields(
                    meta,
                    ls,
                    {"full_name": full_name, "cpf": cpf, "birth_date": birth},
                )
            else:
                logger.warning("LEAD_DATA incompleto/CPF inválido phone=%s", phone)

        elif action == "FOLLOWUP_DOC":
            raw_course = str(
                ls.get("curso_escolhido") or data.get("course") or "Pós-Graduação EAD Faveni"
            ).strip()
            course = resolve_catalog_name(raw_course) or raw_course
            # Se action_data trouxe dados, grava no party correto antes de resolver.
            ad_name = str(data.get("full_name") or "").strip()
            ad_cpf = normalize_cpf(str(data.get("cpf") or "")) or ""
            ad_birth = str(data.get("birth_date") or "").strip()
            if ad_name or ad_cpf or ad_birth:
                from app.lead_data import apply_extracted_contract_fields

                apply_extracted_contract_fields(
                    meta,
                    ls,
                    {
                        k: v
                        for k, v in {
                            "full_name": ad_name,
                            "cpf": ad_cpf,
                            "birth_date": ad_birth,
                        }.items()
                        if v
                    },
                )
            party = resolve_contract_party(meta, ls, push_name=push_name)
            aluno = party["aluno_nome"]
            comprador = party["comprador_nome"] or push_name
            cpf = party["cpf"]
            birth = party["birth_date"]
            if not (aluno and cpf and birth):
                logger.warning("FOLLOWUP_DOC sem dados phone=%s", phone)
                reply = contract_data_request_reply(meta, ls)
            else:
                ls["curso_escolhido"] = course
                from app.desconto_negocio import acordo_pct_from_meta

                get_scheduler().schedule_document(
                    phone=phone,
                    lead_name=aluno,
                    aluno_nome=aluno,
                    comprador_nome=comprador,
                    cpf=cpf,
                    birth_date=birth,
                    course=course,
                    with_checkout=True,
                    desconto_pct=acordo_pct_from_meta(meta),
                )
                meta["pending_contract"] = True
                meta["course"] = course
                delivery_ran = True
                logger.info(
                    "FOLLOWUP_DOC agendado phone=%s course=%s aluno=%s",
                    phone,
                    course,
                    aluno,
                )

        elif action == "CHECKOUT_READY":
            course = str(ls.get("curso_escolhido") or data.get("course") or "Pós-Graduação EAD Faveni").strip()
            party = resolve_contract_party(meta, ls, push_name=push_name)
            name = party["aluno_nome"] or push_name
            from app.desconto_negocio import acordo_pct_from_meta

            session = create_checkout(
                phone,
                course_label=course,
                lead_name=name or "",
                desconto_pct=acordo_pct_from_meta(meta),
                meta=meta,
            )
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

    def _register_handoff_now(
        self,
        *,
        phone: str,
        meta: dict,
        motivo: str,
        push_name: str = "",
    ) -> dict:
        ls = meta.get("lead_state") or {}
        record = register_handoff_request(
            phone=phone,
            nome=ls.get("nome") or push_name or None,
            motivo=motivo or meta.get("handoff_reason") or "geral",
            curso=ls.get("curso_escolhido") or ls.get("curso_recomendado"),
            lead_summary={
                "graduacao": ls.get("graduacao"),
                "area_interesse": ls.get("area_interesse"),
                "objetivo": ls.get("objetivo"),
                "curso_escolhido": ls.get("curso_escolhido"),
                "etapa": meta.get("etapa"),
                "briefing": meta.get("briefing") or "",
                "compra_atual": meta.get("compra_atual"),
            },
            settings=self.settings,
        )
        meta["handoff_request_id"] = record.get("id")
        meta["handoff_registrado"] = True
        meta["_handoff_registered_this_turn"] = True
        # Notifica especialistas (falha não afeta o lead).
        try:
            asyncio.create_task(
                self._notify_handoff_specialists(
                    phone=phone,
                    meta=meta,
                    motivo=motivo or meta.get("handoff_reason") or "geral",
                    push_name=push_name,
                ),
                name=f"notify-handoff-{phone[-4:]}",
            )
        except Exception:  # noqa: BLE001
            logger.exception("agendar notify handoff falhou phone=%s", phone)
        return record

    def _save_pending_offer(self, meta: dict, agent: AgentResponse) -> None:
        """Fonte principal: offer no JSON. infer_offer_from_reply só como reserva."""
        offer = normalize_offer(agent.offer.model_dump() if agent.offer else None)
        source = "json"
        if not offer:
            offer = infer_offer_from_reply(agent.reply or "")
            source = "infer_reply"
        if offer:
            offer["created_turn"] = int(meta.get("turn_count") or 0)
            meta["pending_offer"] = offer
            if source == "infer_reply":
                logger.info(
                    "pending_offer gravada type=%s source=infer_reply (modelo omitiu offer)",
                    offer.get("type"),
                )
            else:
                logger.info("pending_offer gravada type=%s source=json", offer.get("type"))
        else:
            logger.info("pending_offer ausente (sem offer JSON e infer falhou)")

    def _schedule_briefing_refresh(self, phone: str) -> None:
        """Atualiza meta.briefing em segundo plano (não atrasa a resposta)."""

        async def _run() -> None:
            try:
                meta = self.memory.get_meta(phone)
                history = self.memory.get_history(phone)
                previous = str(meta.get("briefing") or "")
                model = getattr(self.settings, "briefing_model", None) or "openai/gpt-4.1-mini"
                new_b = await refresh_briefing(
                    self.llm,
                    previous=previous,
                    recent_messages=history[-8:],
                    matriculas=list(meta.get("matriculas") or []),
                    model=model,
                )
                meta = self.memory.get_meta(phone)
                meta["briefing"] = new_b
                self.memory.set_meta(phone, meta)
                logger.info("briefing atualizado phone=%s chars=%s", phone, len(new_b or ""))
            except Exception:  # noqa: BLE001
                logger.exception("briefing background falhou phone=%s", phone)

        try:
            asyncio.create_task(_run(), name=f"briefing-{phone[-4:]}")
        except Exception:  # noqa: BLE001
            logger.exception("não foi possível agendar briefing phone=%s", phone)

    async def _notify_handoff_specialists(
        self,
        *,
        phone: str,
        meta: dict,
        motivo: str,
        push_name: str = "",
    ) -> None:
        numbers = parse_notify_numbers(
            getattr(self.settings, "handoff_notify_numbers", "") or ""
        )
        if not numbers:
            return
        ls = meta.get("lead_state") or {}
        ca = meta.get("compra_atual") if isinstance(meta.get("compra_atual"), dict) else {}
        msg = build_handoff_notify_message(
            agent_name=self.settings.agent_name,
            lead_nome=ls.get("nome") or push_name,
            lead_phone=phone,
            motivo=motivo,
            curso=(
                ls.get("curso_escolhido")
                or ls.get("curso_recomendado")
                or (ca or {}).get("curso_escolhido")
            ),
            etapa=str(meta.get("etapa") or ""),
            briefing=str(meta.get("briefing") or ""),
        )
        try:
            await notify_numbers(
                self.evo, numbers, msg, exclude_phone=phone
            )
        except Exception:  # noqa: BLE001
            logger.exception("notify handoff falhou phone=%s", phone)

    def _schedule_contract_if_ready(
        self,
        phone: str,
        meta: dict,
        *,
        push_name: str = "",
    ) -> tuple[str, str | None, bool]:
        """Agenda FOLLOWUP_DOC se curso + 3 dados do ALUNO estiverem prontos."""
        ls = ensure_lead_state(meta)
        if missing_contract_fields(meta, ls):
            return "", None, False
        if meta.get("pending_contract") or meta.get("contract_sent"):
            return "", None, False
        raw_course = str(
            ls.get("curso_escolhido")
            or ls.get("curso_recomendado")
            or meta.get("course")
            or ""
        ).strip()
        course = resolve_catalog_name(raw_course) or raw_course
        party = resolve_contract_party(meta, ls, push_name=push_name)
        aluno = party["aluno_nome"]
        comprador = party["comprador_nome"] or push_name
        cpf = party["cpf"]
        birth = party["birth_date"]
        if not (phone and aluno and cpf and birth and course):
            return "", None, False
        from app.desconto_negocio import acordo_pct_from_meta

        get_scheduler().schedule_document(
            phone=phone,
            lead_name=aluno,
            aluno_nome=aluno,
            comprador_nome=comprador,
            cpf=cpf,
            birth_date=birth,
            course=course,
            with_checkout=True,
            desconto_pct=acordo_pct_from_meta(meta),
        )
        meta["pending_contract"] = True
        meta["course"] = course
        # full_name no meta = comprador (não sobrescrever com aluno em 3ª pessoa)
        if party["third"] != "1":
            meta["full_name"] = aluno
        if course:
            ls["curso_escolhido"] = course
        if party["third"] == "1":
            ls["aluno_nome"] = aluno
        meta["lead_state"] = ls
        if party["third"] == "1" and aluno:
            reply = (
                f"Perfeito — com os dados de {aluno} eu já estou preparando o contrato "
                "dela/dele e te mando por aqui em alguns minutinhos, junto com o próximo passo."
            )
            # Gênero resolvido evita "dela/dele"
            gen = (ls.get("aluno_genero") or "").casefold()
            if gen == "f":
                reply = (
                    f"Perfeito — com os dados de {aluno} eu já estou preparando o contrato "
                    "dela e te mando por aqui em alguns minutinhos, junto com o próximo passo."
                )
            elif gen == "m":
                reply = (
                    f"Perfeito — com os dados de {aluno} eu já estou preparando o contrato "
                    "dele e te mando por aqui em alguns minutinhos, junto com o próximo passo."
                )
            else:
                reply = (
                    f"Perfeito — com os dados de {aluno} eu já estou preparando o contrato "
                    "e te mando por aqui em alguns minutinhos, junto com o próximo passo."
                )
        else:
            reply = (
                "Perfeito — com seus dados eu já estou preparando o contrato "
                "e te mando por aqui em alguns minutinhos, junto com o próximo passo."
            )
        logger.info(
            "contrato agendado phone=%s course=%s aluno=%s comprador=%s",
            phone,
            course,
            aluno,
            comprador,
        )
        return reply, course, True

    def _execute_pending_contrato(
        self, meta: dict, *, push_name: str = "", phone: str = ""
    ) -> tuple[str, str | None, bool]:
        ls = ensure_lead_state(meta)
        curso = ls.get("curso_escolhido") or ls.get("curso_recomendado") or ""
        canon = resolve_catalog_name(str(curso)) if curso else None
        if canon:
            ls["curso_escolhido"] = canon
        ls["aceite_matricula"] = True
        meta["lead_state"] = ls
        meta["etapa"] = "fechamento"
        meta["objecoes_sem_avanco"] = 0
        meta.pop("pending_offer", None)

        course_out = canon or (str(curso) if curso else None)
        if phone:
            reply, scheduled_course, delivery = self._schedule_contract_if_ready(
                phone, meta, push_name=push_name
            )
            if delivery:
                return reply, scheduled_course or course_out, True
        # Dados pessoais ok mas sem curso (ou sem phone): não prometer entrega.
        if not missing_contract_fields(meta, ls) and not course_out:
            reply = (
                "Perfeito, recebi seus dados. Qual curso você quer seguir "
                "pra eu preparar o contrato?"
            )
            return reply, None, False
        if not missing_contract_fields(meta, ls) and not phone:
            # Teste unitário sem phone — não agenda, não promete job.
            reply = (
                "Perfeito — com seus dados eu já estou preparando o contrato "
                "e te mando por aqui em alguns minutinhos, junto com o próximo passo."
            )
            return reply, course_out, False
        reply = contract_data_request_reply(meta, ls)
        return reply, course_out, False

    def _execute_pending_encaminhamento(
        self,
        phone: str,
        meta: dict,
        *,
        push_name: str = "",
        motivo: str = "especialista",
    ) -> tuple[str, None, bool]:
        ls = ensure_lead_state(meta)
        why = motivo or meta.get("handoff_reason") or "especialista"
        # Encaminhamento de dúvida: NÃO muda a etapa do funil.
        self._register_handoff_now(
            phone=phone, meta=meta, motivo=why, push_name=push_name
        )
        meta["handoff_avisado"] = True
        meta.pop("pending_offer", None)
        reply = handoff_registered_reply(
            nome=ls.get("nome") or push_name or None,
            motivo=why,
        )
        return reply, None, False

    def _spoken_passes_gate(
        self,
        spoken: str,
        *,
        validated_reply: str,
        recent_assistants: list[str],
        meta: dict,
    ) -> bool:
        """Subset de validadores pós-TTS; se falhar, cai para texto."""
        if claims_unbacked_action(
            spoken,
            has_media=False,
            just_entered_handoff=False,
            handoff_avisado=bool(meta.get("handoff_avisado")),
            delivery_ran=False,
            handoff_registered_this_turn=bool(meta.get("_handoff_registered_this_turn")),
            handoff_registrado=bool(meta.get("handoff_registrado")),
            lead_sending_document=False,
        ):
            return False
        if reply_has_invented_policy(spoken):
            return False
        if reply_has_wrong_course_facts(spoken):
            return False
        if reply_looks_like_callback_promise(spoken) or reply_looks_like_delivery_promise(
            spoken
        ):
            return False
        for prior in recent_assistants:
            if prior and replies_nearly_equal(spoken, prior):
                return False
        # spoken muito diferente da reply validada e com inventário errado já coberto
        _ = validated_reply
        return True

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
        user_text: str = "",
    ) -> str:
        self.last_reply_diag = {
            "regen": False,
            "regen_reason": None,
            "stock": False,
            "stock_reason": None,
            "stock_text": None,
        }
        recent_assistants = self._recent_assistant_texts(phone, n=3)
        last_assistant = recent_assistants[0] if recent_assistants else ""
        reason = self._reply_needs_regen(
            reply,
            meta,
            delivery_ran=delivery_ran,
            blocked_promise_reason=blocked_promise_reason,
            last_assistant=last_assistant,
            has_media=has_media,
            just_entered_handoff=just_entered_handoff,
            user_text=user_text,
            recent_assistants=recent_assistants,
        )
        if reason:
            self.last_reply_diag["regen"] = True
            self.last_reply_diag["regen_reason"] = reason
            logger.info("regen reply reason=%s", reason)
            candidate = await self._regenerate_reply(messages, meta, reason)
            check_delivery = (
                delivery_ran
                if reason not in ("promessa_sem_acao", "promessa_lembrete")
                else False
            )

            def _still(text: str) -> str | None:
                if not text:
                    return reason
                still_blocked = None
                if reply_looks_like_callback_promise(text):
                    still_blocked = "promessa_lembrete"
                elif reply_looks_like_delivery_promise(text):
                    still_blocked = "promessa_sem_acao"
                return self._reply_needs_regen(
                    text,
                    meta,
                    delivery_ran=check_delivery,
                    blocked_promise_reason=still_blocked,
                    last_assistant=last_assistant,
                    has_media=has_media,
                    just_entered_handoff=just_entered_handoff,
                    user_text=user_text,
                    recent_assistants=recent_assistants,
                )

            still = _still(candidate) if candidate else reason
            if candidate and not still:
                meta["stock_streak"] = 0
                self._maybe_mark_handoff_avisado(
                    meta, just_entered_handoff=just_entered_handoff
                )
                return candidate

            # 2ª regeneração: responder direto à última mensagem do lead.
            logger.info("regen 2ª tentativa reason=%s still=%s", reason, still)
            second_msgs = list(messages) + [
                {
                    "role": "system",
                    "content": (
                        "Sua resposta anterior ainda violou uma regra. "
                        "Responda DIRETAMENTE à última mensagem do lead, "
                        "sem meta-fala (catálogo/tabela/regras), sem inventar "
                        "ação, preço ou política. "
                        "Responda de novo APENAS com o JSON do schema "
                        "(reply + state_update + action). Na maioria dos casos action=null."
                    ),
                }
            ]
            second_agent = await self._call_agent_json(second_msgs)
            second = (second_agent.reply or "").strip()
            if looks_like_json(second):
                second = ""
            still2 = _still(second) if second else (still or reason)
            if second and not still2:
                meta["stock_streak"] = 0
                self._maybe_mark_handoff_avisado(
                    meta, just_entered_handoff=just_entered_handoff
                )
                return second

            stock_from = second or candidate or reply
            stock_reason = still2 or still or reason
            logger.info("regen falhou 2x — stock reason=%s", stock_reason)
            stock = self._apply_stock_fallback(
                meta, stock_reason, stock_from, user_text=user_text
            )
            self.last_reply_diag["stock"] = True
            self.last_reply_diag["stock_reason"] = (
                "loop_stock" if meta.get("handoff_reason") == "loop_stock" else stock_reason
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

        # Números internos (especialistas) não abrem funil de venda.
        notify_nums = parse_notify_numbers(
            getattr(self.settings, "handoff_notify_numbers", "") or ""
        )
        if is_internal_number(phone, notify_nums):
            logger.info("mensagem de número interno ignorada phone=%s", phone)
            return ""

        meta = self.memory.get_meta(phone)
        # Qualquer resposta cancela retomadas/primeiro_contato pendentes.
        try:
            from app.outbound_cadence import cancel_retomadas

            n_cancel = cancel_retomadas(phone, get_scheduler())
            if n_cancel:
                meta["proxima_retomada_at"] = None
                logger.info("retomadas canceladas phone=%s n=%s", phone, n_cancel)
        except Exception:  # noqa: BLE001
            logger.exception("falha ao cancelar retomadas phone=%s", phone)

        # Inbox: atendimento humano — registra lead e não responde com a IA.
        if meta.get("ai_paused"):
            from datetime import datetime, timezone

            self.memory.append(phone, "user", user_text)
            meta["inbox_updated_at"] = datetime.now(timezone.utc).isoformat()
            self.memory.set_meta(phone, meta)
            logger.info("ai_paused — mensagem só registrada phone=%s", phone)
            return ""

        # Opt-out explícito
        if re.search(
            r"(?i)\b("
            r"n[aã]o\s+tenho\s+interesse|n[aã]o\s+pedi\s+(?:isso|contato)|"
            r"para\s+de\s+(?:me\s+)?(?:mandar|enviar)|stop\b|opt[\s\-]?out|"
            r"n[aã]o\s+quero\s+(?:mais\s+)?(?:receber|mensagem)"
            r")\b",
            user_text or "",
        ):
            meta["opt_out"] = True
            meta["retomadas_paused"] = True
            ls_opt = ensure_lead_state(meta)
            reply = (
                f"Desculpa o incômodo"
                + (f", {(ls_opt.get('nome') or push_name or '').split()[0]}" if (ls_opt.get("nome") or push_name) else "")
                + ". Não vou mais te enviar mensagens por aqui. "
                "Se mudar de ideia, é só me chamar."
            )
            self.memory.set_meta(phone, meta)
            self.memory.append(phone, "user", user_text)
            self.memory.append(phone, "assistant", reply)
            await self.evo.send_text(phone, reply, delay_ms=0)
            return reply

        ls = ensure_lead_state(meta)
        if push_name and not ls.get("nome"):
            # não assume nome legal; só contexto
            pass

        last_assistant = self._last_assistant_text(phone)
        recent_assistants = self._recent_assistant_texts(phone, n=3)
        mark_refused_fields(meta, lead_text=user_text, last_agent=last_assistant)
        ls = meta.get("lead_state") or ls
        meta["_phone"] = phone
        meta["_push_name"] = push_name
        meta.pop("_handoff_registered_this_turn", None)
        meta["turn_count"] = int(meta.get("turn_count") or 0) + 1
        apply_third_person_flags(ls, user_text)
        if meta.get("etapa") == "matriculado" and (
            lead_wants_new_purchase(user_text) or ls.get("aluno_e_terceiro")
        ):
            begin_new_purchase(meta, ls)
            logger.info("reabre funil a partir de matriculado phone=%s", phone)
        meta["lead_state"] = ls

        # Extrai dados pessoais ANTES de oferta pendente / LLM.
        extracted = extract_contract_fields_from_text(user_text)
        if extracted:
            apply_extracted_contract_fields(meta, ls, extracted)
            ls = meta.get("lead_state") or ls
            logger.info(
                "dados pessoais extraídos phone=%s keys=%s",
                phone,
                sorted(extracted.keys()),
            )

        etapa_antes = meta.get("etapa") or "abertura"
        pending = meta.get("pending_offer") if isinstance(meta.get("pending_offer"), dict) else None
        force_skip_finalize = False
        write_resumo_now = False
        lead_irritado_turn = False
        just_entered_handoff = False
        reply = ""
        course: str | None = None
        blocked_promise_reason: str | None = None
        delivery_ran = False
        messages: list[dict] = []
        has_media = bool(has_image or has_document)
        agent: AgentResponse | None = None

        # pending_offer: classificação no LLM (resposta_a_oferta); não expira por 1 turno.
        pending_executed = False

        # Dados completos nesta mensagem → agenda (aceite implícito se oferta pendente).
        if (
            extracted
            and not meta.get("pending_contract")
            and not meta.get("contract_sent")
            and not missing_contract_fields(meta, ls)
            and (
                meta.get("etapa") == "fechamento"
                or ls.get("aceite_matricula")
                or (pending and str(pending.get("type") or "") == "contrato")
            )
        ):
            if pending and str(pending.get("type") or "") == "contrato":
                reply, course, delivery_ran = self._execute_pending_contrato(
                    meta, push_name=push_name, phone=phone
                )
                pending_executed = True
                force_skip_finalize = True
                self.last_reply_diag = {
                    "regen": False,
                    "regen_reason": None,
                    "stock": False,
                    "stock_reason": None,
                    "stock_text": None,
                    "pending_offer_executed": True,
                    "contract_scheduled_from_extract": True,
                }
            else:
                sched_reply, sched_course, scheduled = self._schedule_contract_if_ready(
                    phone, meta, push_name=push_name
                )
                if scheduled:
                    reply = sched_reply
                    course = sched_course
                    delivery_ran = True
                    force_skip_finalize = True
                    pending_executed = True
                    self.last_reply_diag = {
                        "regen": False,
                        "regen_reason": None,
                        "stock": False,
                        "stock_reason": None,
                        "stock_text": None,
                        "pending_offer_executed": False,
                        "contract_scheduled_from_extract": True,
                    }

        # "Vc registrou?" — resposta baseada no registro real, sem LLM se possível.
        if (
            not force_skip_finalize
            and lead_asks_if_registered(user_text)
            and not lead_affirms_offer(user_text)
        ):
            if meta.get("handoff_registrado"):
                reply = (
                    "Sim — seu pedido está registrado; o especialista do polo "
                    "te chama por aqui."
                )
                force_skip_finalize = True
            else:
                meta["pending_offer"] = {
                    "type": "encaminhamento",
                    "motivo": meta.get("handoff_reason") or "especialista",
                    "created_turn": int(meta.get("turn_count") or 0),
                }
                reply = (
                    "Ainda não registrei. Quer que eu registre seu pedido agora "
                    "para um especialista do polo te atender por aqui?"
                )
                force_skip_finalize = True
                logger.info("reoffer encaminhamento após pergunta registrou phone=%s", phone)

        if not force_skip_finalize:
            facts_block = format_facts_block(facts_for_lead_state(ls))
            fixed, variable = build_system_prompt_parts(
                etapa=meta.get("etapa") or etapa_antes,
                lead_state=ls,
                meta_flags={
                    "pending_contract": meta.get("pending_contract"),
                    "contract_sent": meta.get("contract_sent"),
                    "desconto_respondido": meta.get("desconto_respondido"),
                    "desconto_negociacao_nivel": meta.get("desconto_negociacao_nivel"),
                    "desconto_oferta_atual_pct": meta.get("desconto_oferta_atual_pct"),
                    "comercial_retorno": meta.get("comercial_retorno"),
                    "handoff_reason": meta.get("handoff_reason"),
                    "handoff_avisado": meta.get("handoff_avisado"),
                    "handoff_registrado": meta.get("handoff_registrado"),
                    "campos_recusados": meta.get("campos_recusados") or [],
                    "matriculas": meta.get("matriculas") or [],
                    "compra_atual": meta.get("compra_atual"),
                    "pending_offer": pending,
                    "briefing": meta.get("briefing"),
                },
                agent_name=self.settings.agent_name,
                agent_gender=self.settings.agent_gender,
                facts_block=facts_block or "",
            )
            hist_limit = int(
                getattr(self.settings, "prompt_history_messages", 12) or 12
            )
            history = self.memory.get_history(phone)[-hist_limit:]
            history_empty = not history
            messages = [build_cached_system_message(fixed, variable)]
            for h in history:
                role = str(h.get("role") or "assistant")
                content = str(h.get("content") or "")
                if h.get("source") == "human" or role == "operator":
                    role = "assistant"
                    content = f"[Mensagem do atendente humano]\n{content}"
                if role not in ("user", "assistant", "system"):
                    role = "assistant"
                messages.append({"role": role, "content": content})
            if push_name and history_empty:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"O lead se apresenta no WhatsApp como: {push_name}. "
                            "Use o primeiro nome com naturalidade."
                        ),
                    }
                )
            if inbound_audio:
                messages.append(
                    {
                        "role": "system",
                        "content": "O lead mandou ÁUDIO (já transcrito). Mantenha empatia e calor.",
                    }
                )
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
            if pending:
                otype = str(pending.get("type") or "oferta")
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            f"Há oferta PENDENTE do turno anterior: type={otype}. "
                            "Classifique a mensagem do lead em resposta_a_oferta: "
                            '"aceitou" | "recusou" | "outro_assunto". '
                            "Adoraria/bora/manda/fechado/quero sim = aceitou."
                        ),
                    }
                )
            if write_resumo_now:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "O lead ACEITOU o resumo oferecido. Escreva o resumo COMPLETO "
                            "NESTA mensagem (curso, carga, mensalidade da faixa, 100% online, "
                            "troca em 90 dias, documentos). offer=null. action=null."
                        ),
                    }
                )
            if (
                lead_soft_deferral(user_text)
                and not lead_asks_explicit_callback(user_text)
                and not lead_says_farewell_or_space(user_text)
            ):
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "O lead deu uma ESQUIVA VAGA de momento (ex.: 'agora não', "
                            "'momento melhor') — NÃO encerre a conversa e NÃO diga só "
                            "'quando quiser me chama'. Acolha em 1 frase e ISOLA a "
                            "objeção real com UMA pergunta: é valor, tempo/rotina, "
                            "dúvida do curso ou outra coisa? "
                            "state_update: objecao_ativa=vou_pensar (ou a categoria "
                            "real se ele já deixar claro)."
                        ),
                    }
                )
            messages.append({"role": "user", "content": user_text})

            agent = await self._call_agent_json(messages)

            lead_irritado_turn = bool(agent.state_update.get("lead_irritado"))
            merge_state_update(ls, agent.state_update)
            apply_third_person_flags(ls, user_text)
            apply_enrollment_intent(ls, user_text)
            # Só reabre se ainda estiver em matriculado (evita apagar state_update).
            if meta.get("etapa") == "matriculado" and (
                lead_wants_new_purchase(user_text) or ls.get("aluno_e_terceiro")
            ):
                begin_new_purchase(meta, ls)
            # Canonicaliza curso se veio no update
            if ls.get("curso_escolhido"):
                canon = resolve_catalog_name(str(ls["curso_escolhido"]))
                if canon:
                    ls["curso_escolhido"] = canon
            # Sync compra_atual ↔ lead_state
            ca = ensure_compra_atual(meta)
            sync_ls_into_compra_atual(ls, ca)
            ca["etapa"] = meta.get("etapa") or ca.get("etapa")
            meta["compra_atual"] = ca
            meta["lead_state"] = ls
            advance_etapa(meta, handoff_max_objecoes=self.settings.handoff_max_objecoes)
            meta.pop("_reopen_purchase", None)
            just_entered_handoff = (
                meta.get("etapa") == "handoff_humano" and etapa_antes != "handoff_humano"
            )
            if meta.get("etapa") == "handoff_humano":
                logger.info(
                    "handoff_humano phone=%s summary=%s", phone, summarize_lead(meta)
                )

            # Classifica resposta à oferta pendente (modelo → lexical).
            if pending and not pending_executed:
                rao = agent.resposta_a_oferta
                if rao is None:
                    # encaminhamento: também aceita lead_accepts_specialist
                    otype = str(pending.get("type") or "")
                    if otype == "encaminhamento" and lead_accepts_specialist(user_text):
                        rao = "aceitou"
                    elif otype == "encaminhamento" and lead_refuses_handoff(user_text):
                        rao = "recusou"
                    else:
                        rao = classify_offer_response_fallback(user_text)
                        if rao:
                            logger.info(
                                "resposta_a_oferta fallback lexical=%s phone=%s",
                                rao,
                                phone,
                            )
                else:
                    logger.info(
                        "resposta_a_oferta modelo=%s phone=%s", rao, phone
                    )
                otype = str(pending.get("type") or "")
                if rao == "aceitou":
                    if otype == "contrato":
                        reply, course, delivery_ran = self._execute_pending_contrato(
                            meta, push_name=push_name, phone=phone
                        )
                        pending_executed = True
                        logger.info(
                            "pending_offer executada type=contrato phone=%s", phone
                        )
                    elif otype == "encaminhamento":
                        reply, course, delivery_ran = (
                            self._execute_pending_encaminhamento(
                                phone,
                                meta,
                                push_name=push_name,
                                motivo=str(pending.get("motivo") or "especialista"),
                            )
                        )
                        just_entered_handoff = meta.get("etapa") == "handoff_humano"
                        pending_executed = True
                        logger.info(
                            "pending_offer executada type=encaminhamento phone=%s",
                            phone,
                        )
                    elif otype == "resumo":
                        meta.pop("pending_offer", None)
                        write_resumo_now = True
                        # reusa reply do modelo se já veio resumo; senão agent.reply
                        reply = (agent.reply or "").strip() or reply
                    else:
                        meta.pop("pending_offer", None)
                elif rao in ("recusou", "outro_assunto"):
                    meta.pop("pending_offer", None)
                    logger.info(
                        "pending_offer expirada motivo=%s phone=%s", rao, phone
                    )
                # rao None → mantém pending_offer

            if not pending_executed:
                reply, course, blocked_promise_reason, delivery_ran = self._apply_actions(
                    phone,
                    meta,
                    agent,
                    push_name,
                    user_text=user_text,
                    last_assistant=last_assistant,
                )
                # Grava offer para o próximo turno (antes do áudio/TTS).
                self._save_pending_offer(meta, agent)
            else:
                blocked_promise_reason = None
                self.last_reply_diag = {
                    "regen": False,
                    "regen_reason": None,
                    "stock": False,
                    "stock_reason": None,
                    "stock_text": None,
                    "pending_offer_executed": True,
                }

            if meta.get("_handoff_registered_this_turn"):
                just_entered_handoff = (
                    just_entered_handoff or meta.get("etapa") == "handoff_humano"
                )

            if not pending_executed:
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
                    user_text=user_text,
                )
            elif not (reply or "").strip():
                reply = (agent.reply or "").strip() or (
                    "Me conta o que você precisa agora?"
                )
        else:
            self.last_reply_diag = {
                "regen": False,
                "regen_reason": None,
                "stock": False,
                "stock_reason": None,
                "stock_text": None,
                "pending_offer_executed": True,
            }

        # Soft deferral / callback: nunca vazar placeholder interno ao lead.
        # Retomada SÓ se o lead pedir retorno explícito. Esquiva vaga ≠ “me chama”.
        ls_now = meta.get("lead_state") or {}
        soft_text = lead_soft_deferral(user_text)
        explicit_cb = lead_asks_explicit_callback(user_text)
        farewell = lead_says_farewell_or_space(user_text)
        obj = ls_now.get("objecao_ativa")
        if obj not in (None, "", "vou_pensar"):
            meta["soft_deferral_count"] = 0

        def _door_open_reply() -> str:
            first = (ls_now.get("nome") or push_name or "").split()
            greet = f"{first[0]}, " if first else ""
            return (
                f"{greet}sem problema. Quando fizer sentido pra você, "
                "é só me chamar aqui — fico à disposição."
            )

        def _promises_callback(text: str) -> bool:
            return bool(
                re.search(
                    r"(?i)\b(te\s+chamo|volto\s+a\s+te|te\s+aviso|te\s+cobro)\b",
                    text or "",
                )
            )

        declined_chase = False
        if soft_text and not explicit_cb and not farewell:
            n_soft = int(meta.get("soft_deferral_count") or 0) + 1
            meta["soft_deferral_count"] = n_soft
            if n_soft <= 1:
                # 1ª esquiva: investiga a objeção. Sem promessa de retorno.
                if reply_looks_lazy_close(reply) or not (reply and "?" in reply):
                    reply = soft_deferral_probe_reply(
                        (ls_now.get("nome") or push_name or "")
                    )
                    logger.info("soft_deferral probe phone=%s n=%s", phone, n_soft)
                elif _promises_callback(reply):
                    reply = soft_deferral_probe_reply(
                        (ls_now.get("nome") or push_name or "")
                    )
            else:
                # 2ª+ sem pedido de retorno: respeita o “não por agora”.
                declined_chase = True
                if (
                    reply_looks_lazy_close(reply)
                    or _promises_callback(reply)
                    or (reply and "?" in reply)
                ):
                    reply = _door_open_reply()
                logger.info("soft_deferral respect phone=%s n=%s", phone, n_soft)
            wants_callback = False
        elif farewell and not explicit_cb:
            declined_chase = True
            wants_callback = False
        else:
            wants_callback = bool(explicit_cb)
            # Lead voltou a conversar → libera chase pausado por esquiva anterior.
            if meta.get("retomadas_paused") and not meta.get("opt_out"):
                meta["retomadas_paused"] = False

        # Sanidade: nunca enviar texto de controle interno ao WhatsApp.
        if reply and re.search(r"(?i)modo\s*demo|[\(\[]\s*demo\s*[\)\]]", reply):
            reply = re.sub(
                r"(?i)\s*(?:[\(\[]?\s*modo\s*demo\s*[\)\]]?|[\(\[]\s*demo\s*[\)\]])",
                "",
                reply,
            )
            reply = re.sub(r"(?i)\s*em alguns minutinhos\.?", "", reply)
            reply = re.sub(r"[ \t]{2,}", " ", reply)
            reply = re.sub(r"\n{3,}", "\n\n", reply).strip(" \n\t.-")
            logger.warning("stripped internal demo wording phone=%s", phone)

        if wants_callback and not meta.get("opt_out"):
            try:
                from app.outbound_cadence import schedule_think_followup

                delay = schedule_think_followup(
                    phone, meta, get_scheduler(), user_text=user_text
                )
                meta["_retomada_agendada"] = True
                meta["retomadas_paused"] = False
                if blocked_promise_reason == "promessa_lembrete":
                    blocked_promise_reason = None
                # Confirma retorno só se o lead pediu explicitamente e a reply
                # ainda não combinou — NUNCA cite "modo demo" / timing interno.
                if explicit_cb and not re.search(
                    r"(?i)\b(te\s+chamo|retorno|volto\s+a\s+te|te\s+aviso)\b",
                    reply or "",
                ):
                    reply = (
                        (reply or "").rstrip()
                        + "\n\nCombinado — te chamo de novo por aqui."
                    ).strip()
                logger.info("retomada agendada phone=%s delay=%ss", phone, int(delay))
            except Exception:  # noqa: BLE001
                logger.exception("falha ao agendar retomada phone=%s", phone)
        elif soft_text or declined_chase or farewell:
            # Lead fechou o momento (ou se despediu) sem pedir retorno:
            # cancela chase pendente e NÃO agenda silêncio do funil.
            try:
                from app.outbound_cadence import cancel_retomadas

                cancel_retomadas(phone, get_scheduler())
                meta["proxima_retomada_at"] = None
                if declined_chase or farewell:
                    meta["retomadas_paused"] = True
                logger.info(
                    "retomadas canceladas (declinio/esquiva) phone=%s paused=%s",
                    phone,
                    bool(meta.get("retomadas_paused")),
                )
            except Exception:  # noqa: BLE001
                logger.exception("falha ao cancelar retomadas phone=%s", phone)
        elif not meta.get("opt_out") and not meta.get("pending_contract"):
            # Reagenda silêncio do funil (qualquer reply cancela as anteriores).
            try:
                from app.outbound_cadence import schedule_silence_followups

                schedule_silence_followups(
                    phone, meta, get_scheduler(), settings=self.settings
                )
            except Exception:  # noqa: BLE001
                logger.exception("falha ao agendar silence followups phone=%s", phone)

        self.memory.set_meta(phone, meta)

        self.memory.append(phone, "user", user_text)
        self.memory.append(phone, "assistant", reply)
        self._schedule_briefing_refresh(phone)

        want_audio = self._should_reply_audio(
            phone=phone,
            inbound_was_audio=inbound_audio,
            reply=reply,
            course=course,
        )
        if want_audio:
            try:
                allow_tags = self._allow_expression_tags(meta, reply, lead_irritado_turn)
                ls_audio = meta.get("lead_state") or {}
                spoken = await to_spoken_script(
                    self.llm,
                    reply,
                    agent_name=self.settings.agent_name,
                    agent_gender=self.settings.agent_gender,
                    allow_expression_tags=allow_tags,
                    last_audio_opening=str(meta.get("last_audio_opening") or ""),
                    lead_name=str(
                        ls_audio.get("nome") or meta.get("full_name") or push_name or ""
                    ),
                    aluno_nome=str(ls_audio.get("aluno_nome") or ""),
                )
                if not self._spoken_passes_gate(
                    spoken,
                    validated_reply=reply,
                    recent_assistants=recent_assistants,
                    meta=meta,
                ):
                    logger.warning("tts gate falhou — enviando texto validado")
                    raise RuntimeError("spoken_gate_failed")
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
