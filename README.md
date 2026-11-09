# Controle de Abastecimento

Aplicação web para registrar abastecimentos, acompanhar eficiência e custo por quilômetro e estimar a melhor proporção entre etanol e gasolina para um veículo flex.

O projeto reproduz a lógica validada na planilha **Controle Abastecimento**: cada ciclo usa a composição e o custo médio do tanque anterior. Alterar ou excluir um registro histórico recalcula automaticamente todos os registros posteriores.

## Funcionalidades do MVP

- Cadastro, edição e exclusão de abastecimentos com tanque cheio.
- Composição do tanque: gasolina A, etanol anidro e etanol hidratado.
- Consumo em km/L, preço do litro consumido e custo por quilômetro.
- Limites oficial, pessoal e faixa de decisão neutra.
- Dashboard responsivo com gráficos de eficiência, custo e composição.
- Otimizador por tipo de trajeto, com requisito mínimo de cobertura da amostra.
- Importação de JSON, XLSX e CSV.
- Exportação para CSV e download de backup SQLite (somente superusuário).
- Execução em um único container Docker.

## Executar com Docker

1. Copie `.env.example` para `.env`.
2. Troque `DJANGO_SECRET_KEY` por uma chave longa e aleatória. Sem isso o container não sobe:
   a aplicação recusa chaves ausentes, curtas ou iguais ao exemplo do repositório.

   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(64))"
   ```

3. Execute:

```bash
docker compose up --build -d
```

4. Crie o seu usuário (veja [Acesso](#acesso)) e acesse `http://localhost:8000`.

Por padrão a porta é publicada só em `127.0.0.1`. Para acessar pela rede local, defina `APP_BIND=0.0.0.0` no `.env`.

Para acompanhar a inicialização:

```bash
docker compose logs -f app
```

O SQLite fica no volume Docker `fuel_data`. Recriar o container não remove o banco, mas o volume não substitui um backup externo.

## Executar localmente

Requer Python 3.12 ou superior.

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements.txt
export DJANGO_DEBUG=True   # PowerShell: $env:DJANGO_DEBUG="True"
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

No Linux/macOS, ative o ambiente com `source .venv/bin/activate`.

## Importar a planilha existente

Exporte a planilha como `.xlsx` ou use um snapshot JSON no formato retornado pela API do Google Sheets. Os dados importados ficam somente no SQLite local e não devem ser adicionados ao Git.

```bash
python manage.py import_fuelings caminho/Controle-Abastecimento.xlsx --replace
```

O importador lê a aba `Abastecimentos` e utiliza as colunas de entrada: data, posto, trajeto, uso do ar-condicionado, hodômetro, volumes, preços e teor de etanol anidro.

Para importar em uma aplicação já iniciada pelo Docker:

```bash
docker compose cp caminho/Controle-Abastecimento.xlsx app:/tmp/abastecimentos.xlsx
docker compose exec app python manage.py import_fuelings /tmp/abastecimentos.xlsx --replace
```

Para conferir um snapshot JSON contra os resultados calculados:

```bash
python manage.py validate_snapshot caminho/abastecimentos.json
```

## Acesso

Todas as telas exigem login, e apenas `/health/` é pública. Para criar o seu usuário:

```bash
docker compose exec app python manage.py createsuperuser
```

- O botão **Sair** fica no menu superior.
- Depois de 5 senhas erradas, o IP de origem fica bloqueado por 1 hora. Os valores são configuráveis em `AXES_FAILURE_LIMIT` e `AXES_COOLOFF_MINUTES`. Para desbloquear antes do prazo:

  ```bash
  docker compose exec app python manage.py axes_reset
  ```

- Não existe redefinição de senha por e-mail. Para trocar a senha, use `python manage.py changepassword <usuário>`.

### Cloudflare Tunnel

O TLS termina na Cloudflare, e o `cloudflared` entrega HTTP ao app. Para esse cenário, configure no `.env`:

```env
APP_BEHIND_CLOUDFLARE=True
DJANGO_ALLOWED_HOSTS=seu.dominio.com.br,localhost,127.0.0.1
DJANGO_CSRF_TRUSTED_ORIGINS=https://seu.dominio.com.br
```

Com isso, os cookies passam a ser `Secure`, o app reconhece o HTTPS pelo `X-Forwarded-Proto` e o bloqueio de força bruta usa o IP real do visitante (`CF-Connecting-IP`), e não o IP do `cloudflared`.

- O `CF-Connecting-IP` só é aceito em conexões vindas de endereços internos (loopback, redes Docker e LAN). Mantenha `APP_BIND=127.0.0.1` quando o `cloudflared` roda no mesmo host.
- No painel da Cloudflare, ative **Always Use HTTPS**. Ative também o HSTS, no painel ou com `SECURE_HSTS_SECONDS` no `.env`.
- Recomendado para uso pessoal: proteja o hostname com **Cloudflare Access** (Zero Trust → Access → Applications), com política liberando só o seu e-mail. Assim a Cloudflare exige um código por e-mail antes de qualquer requisição chegar ao app, o que soma uma segunda camada ao login. Se usar Access, libere `/health/` apenas se tiver monitoramento externo.
- A Content Security Policy do app bloqueia scripts externos. Recursos da Cloudflare que injetam JavaScript na página (Rocket Loader, Web Analytics automático, Email Obfuscation) deixarão de funcionar; mantenha-os desligados para este hostname.

## Dados e backups

- `data/db.sqlite3` (ou o volume Docker `fuel_data`): banco local, fora do Git.
- `/exportar/csv/`: exporta o histórico em formato tabular.
- `.env`: configuração local e segredos, ignorados pelo Git.

### Backup

Hoje o backup é **manual**: não há rotina agendada. Em **Configurações → Baixar backup SQLite** (`/backup/`, visível só para superusuário), o app gera uma cópia consistente do banco e a entrega como download:

- a cópia inclui abastecimentos, veículo e usuários (com as senhas em hash);
- as sessões de login e o registro de tentativas de acesso são esvaziados, porque a chave de sessão é o próprio cookie de login e quem tivesse o arquivo poderia entrar como você;
- a resposta não é guardada em cache (`Cache-Control: no-store`).

O volume Docker sobrevive à recriação do container, mas não substitui um backup fora da máquina. Guarde os arquivos baixados num local cifrado. A variável `BACKUP_DIR` está reservada para uma futura rotina automática e ainda não é usada.

Para restaurar um arquivo baixado:

```bash
docker compose stop app
docker compose cp controle-abastecimento-AAAA-MM-DD.sqlite3 app:/app/data/db.sqlite3
docker compose start app
```

Depois da restauração, é preciso fazer login de novo (as sessões não fazem parte do backup).

O repositório é público. Não publique o banco SQLite, exportações da planilha ou arquivos de backup.

## Testes

```bash
python manage.py test
DJANGO_SECRET_KEY=<chave> APP_BEHIND_CLOUDFLARE=True python manage.py check --deploy
```

`manage.py test` não precisa de `.env`: usa uma chave descartável e arquivos estáticos sem manifest.

## Estrutura

```text
config/                 Configuração do Django
fuelings/               Modelos, cálculos, telas e importadores
templates/              Interface HTML
static/                 Estilos, JavaScript e Chart.js (vendor/, versão 4.4.7 do npm)
scripts/entrypoint.sh    Inicialização do container
compose.yaml             Serviço único e volume SQLite
```
