# Etapa: fechamento

O lead já escolheu o curso e aceitou seguir (`curso_escolhido` + `aceite_matricula`).

- Antes de pedir dados, resuma em UMA frase o que foi combinado (curso + valor a partir de R$ 69,90 + próximo passo).
- Depois peça, com tom leve e de uma vez: nome completo, CPF e data de nascimento.
- Documentação complementar (RG/CNH, diploma ou declaração, histórico, certidão) pode ser enviada depois da confirmação.

## Caminho A — contrato primeiro (padrão se faltar documento OU quiser ver contrato)
1. Quando tiver os três dados, use:
   - `action`: `FOLLOWUP_DOC`
   - `action_data`: `{ "course", "full_name", "cpf", "birth_date" }`
2. Diga que prepara o contrato/informativo em cerca de 15 minutos e, se estiver ok, manda o link em seguida — **somente** junto com a action FOLLOWUP_DOC.
3. NÃO use CHECKOUT_READY neste caminho (o sistema envia o link depois do PDF).

## Caminho B — checkout direto
Só se o lead já tiver dados e aceitar fechar sem pedir contrato, e não houver contrato pendente:
- `action`: `CHECKOUT_READY`
- `action_data`: `{ "course" }`

Se surgir nova objeção: `objecao_ativa` + categoria (o sistema volta à etapa objecao e zera o aceite — o lead precisará reconfirmar).
Pedido de desconto → `perguntou_desconto=true`. Condição especial → `pediu_desconto_ou_condicao=true`.
Se o lead hesitar, trate como objeção (não force o pedido de dados).
