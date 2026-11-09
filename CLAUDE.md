# Controle de Abastecimento — regras do projeto

Complementa as diretrizes globais (`~/.claude/CLAUDE.md`). Onde houver conflito, vale este arquivo, exceto nas regras de segurança de dados.

## O que é
App Django de uso pessoal, SQLite, em um único container Docker. Produção roda em outro servidor; esta máquina é só ambiente de teste. O repositório é **público**: nunca versionar IPs, domínios internos, segredos, `.env` nem dados reais (CSV de abastecimentos).

## Testes e verificações
- Só no Docker de revisão, sem publicar porta (a 8000 é do contêiner da aplicação local):
  `docker compose -p controle-abastecimento-revisao -f compose.dev.yaml run --rm --no-deps app python manage.py test`, depois `... down` sem `-v`.
- Não rodar no Python do WSL. Não derrubar nem recriar o contêiner `controle-abastecimento-app-1` nem o volume de produção de `compose.yaml`.
- Verificação com dados reais: só leitura, sobre cópia do banco.

## Fluxo de alteração
1. Branch de trabalho a partir da `main` atualizada.
2. Corrigir conforme o relatório de revisão (`docs/revisao-tecnica-2026-11.md`, fora do Git).
3. Testar: suíte completa no Docker de revisão.
4. Subir o container local (`docker compose -f compose.dev.yaml up --build`) para o usuário validar.
5. **Só depois do OK explícito do usuário**: push, PR e merge (merge commit) na `main`. Sem esse OK, parar no passo 4.
6. Conflitos simples: resolver, testar e mesclar. Conflitos complexos: parar e fazer nova rodada de testes com o usuário.
7. Depois do merge: atualizar `docs/revisao-tecnica-2026-11.md` (situação do item, tabelas Em aberto/Resolvidos, plano de ação) e o README se aplicável.

Manter as branches de trabalho. Mexer só no que foi citado.

## Arquivos que nunca vão para commit
- `docs/` (relatório de revisão técnica, mantido fora do Git por ser repositório público; está não rastreado, então nunca usar `git add .` nem `git add -A`).
- `abastecimentos-*.csv` e seus `Zone.Identifier` (dados reais).
- `.env`.
Usar `git add` com arquivos explícitos.

## Ambiente
- `git` sem identidade configurada: commits com `git -c user.name="Luiz Pereira" -c user.email="lhpereira@gmail.com" commit ...`, sem alterar a configuração global.
- Qualquer JS novo precisa ser arquivo em `static/` (CSP sem inline nem CDN).
- Com `APP_BEHIND_CLOUDFLARE=True` os cookies são Secure: o login só funciona pelo domínio, não por `http://IP:porta`.

## Agentes do projeto
`executor-abastecimento` (Sonnet) e `revisor-abastecimento` (Opus), em `.claude/agents/`.
