# ElevenLabs — voz e configs (Edu SDR)

## Voz aprovada (demo)

| Campo | Valor |
|---|---|
| **Voz** | Roberta - For Conversational |
| **Model** | `eleven_v4` |
| **stability** | `0.35` |
| **similarity_boost** | `0.75` |
| **style** | `0` |
| **speed** | `1.0` |

## Tags de expressão (`eleven_v4`)

Permitidas **somente**:

- `[chuckles]`
- `[thoughtful]`

Regras (garantidas no código em `app/speech.py`):

- no máximo **2** por áudio (pode ser zero);
- removidas se a etapa for `handoff_humano` / `aluno_atual`, se `lead_irritado` no turno, ou se o texto pedir/confirmar dados pessoais (nome completo, CPF, nascimento);
- tags existem **só** no texto enviado à ElevenLabs — nunca no histórico nem na mensagem de texto ao lead.

## Fala natural

Antes do TTS, `to_spoken_script` reescreve para áudio casual de WhatsApp (contrações, marcadores leves, reticências, abertura variável). EAD é falado como palavra (`ead`).

## Pós-processamento (nota de voz)

`app/audio_post.py` (ffmpeg):

- OGG/Opus mono, 48 kHz, ~32 kbps;
- passa-alta ~100 Hz e passa-baixa ~7 kHz;
- 300–500 ms de silêncio no início + ~300 ms no fim;
- loudnorm.

Se o ffmpeg falhar, envia o MP3 original (nunca deixa de responder).

### Encoding Evolution (`EVOLUTION_AUDIO_ENCODING`)

Endpoint: `POST /message/sendWhatsAppAudio/{instance}` (PTT).

| Formato enviado | Encoding |
|---|---|
| OGG Opus (pós-ffmpeg) | valor de `EVOLUTION_AUDIO_ENCODING` (padrão **`false`**) |
| MP3 (fallback) | **sempre `true`** (Evolution gera PTT) |

**Smoke na Evolution 2.3.7:** testar OGG com `true` e `false` e confirmar qual chega como nota de voz (bolinha azul de “ouvido”) com melhor qualidade. Padrão atual do repo: `false` (sem re-encode do Opus já no formato de voice note). Se `true` vencer no seu ambiente, ajuste o env no EasyPanel.

```
EVOLUTION_AUDIO_ENCODING=false
```

## Dados e links só por texto

`_should_reply_audio` retorna `False` quando a reply pede/confirma dados pessoais ou contém link. Pedido de CPF → sempre texto.

## Trocar no EasyPanel

```
AGENT_NAME=Edu
AGENT_GENDER=f
ELEVENLABS_MODEL_ID=eleven_v4
ELEVENLABS_VOICE_ID=<id Roberta - For Conversational>
ELEVENLABS_STABILITY=0.35
ELEVENLABS_SIMILARITY=0.75
ELEVENLABS_STYLE=0
ELEVENLABS_SPEED=1.0
EVOLUTION_AUDIO_ENCODING=false
```

Depois: redeploy/restart do serviço `api`.
