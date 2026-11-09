# ElevenLabs — como escolher voz e configs (Edu)

## Peças do sistema

| Peça | O que é | Onde fica |
|---|---|---|
| **Voice ID** | A “pessoa” (timbre, sotaque) | Voices no painel → copiar ID |
| **Model** | O motor que fala com essa voz | `ELEVENLABS_MODEL_ID` |
| **voice_settings** | Expressividade, velocidade, etc. | env / API |

A voz artificial costuma vir de: modelo antigo + stability alta + voz tipo “narrador”.

## Modelo (o mais importante agora)

| Model ID | Quando usar |
|---|---|
| **`eleven_v4`** | **Melhor qualidade / mais humano** (recomendado Pro) |
| `eleven_v4_turbo` | Quase tão bom, mais rápido (WhatsApp) |
| `eleven_multilingual_v2` | Mais antigo; soava “estável demais” na nossa demo |

Estávamos em `multilingual_v2`. Padrão novo do Edu: **`eleven_v4`**.

## Como escolher a voz no site

1. Abra **Voices** / Voice Library.
2. Filtre **Portuguese** / Brazilian se existir.
3. Prefira tags: **Conversational**, **Friendly**, **Warm** — evite News / Narration / Documentary.
4. Teste a frase: *“Oi! Sou o Edu da Faveni. Você busca pós, segunda licenciatura ou graduação?”*
5. Se soar apresentador de TV → troca. Se soar atendente no zap → serve.
6. Copie o **Voice ID** → cole no EasyPanel `ELEVENLABS_VOICE_ID`.

Dica Pro: **Instant Voice Clone** com 1–2 min de você falando natural em PT-BR costuma bater qualquer voz genérica.

## Settings (expressividade)

| Setting | Baixo | Alto | Demo Edu |
|---|---|---|---|
| **stability** | Mais emoção/variação | Mais monótono | **0.30–0.40** |
| **similarity_boost** | Mais “solto” | Mais fiel à voz | **0.75–0.85** |
| **style** | Neutro | Mais “caráter” | **0.25–0.40** |
| **speed** | Mais lento | Mais rápido | **0.92–1.00** |

## Texto também importa

- Frases curtas (WhatsApp).
- Evitar listas longas no áudio.
- Pontuação ajuda a entonação (`!`, `?`, reticências com parcimônia).

## Trocar no EasyPanel

```
ELEVENLABS_MODEL_ID=eleven_v4
ELEVENLABS_VOICE_ID=<id da voz escolhida>
ELEVENLABS_STABILITY=0.35
ELEVENLABS_SIMILARITY=0.8
ELEVENLABS_STYLE=0.35
ELEVENLABS_SPEED=0.95
```

Depois: redeploy/restart do serviço `api`.
