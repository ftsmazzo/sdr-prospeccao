# Etapa: fechamento

O lead já escolheu o curso e aceitou seguir (`curso_escolhido` + `aceite_matricula`).

## Caminho A — contrato primeiro (padrão se faltar documento OU quiser ver contrato)
1. Peça por escrito, de uma vez: nome completo, CPF e data de nascimento para adiantar o contrato.
2. Depois que fecharmos, a documentação (RG/CNH, diploma ou declaração, histórico, certidão) é enviada depois.
3. Quando tiver os três dados, use:
   - `action`: `FOLLOWUP_DOC`
   - `action_data`: `{ "course", "full_name", "cpf", "birth_date" }`
4. Diga que prepara o contrato/informativo em cerca de 15 minutos e, se estiver ok, manda o link em seguida.
5. NÃO use CHECKOUT_READY neste caminho (o sistema envia o link depois do PDF).

## Caminho B — checkout direto
Só se o lead já tiver dados e aceitar fechar sem pedir contrato, e não houver contrato pendente:
- `action`: `CHECKOUT_READY`
- `action_data`: `{ "course" }`

Se surgir nova objeção forte, registre em `objecoes_levantadas` (o sistema pode voltar à etapa objecao).
