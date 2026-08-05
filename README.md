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
- Exportação para CSV e download de backup SQLite.
- Execução em um único container Docker.

## Executar com Docker

1. Copie `.env.example` para `.env`.
2. Troque `DJANGO_SECRET_KEY` por uma chave longa e aleatória.
3. Execute:

```bash
docker compose up --build -d
```

4. Acesse `http://localhost:8000`.

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
python manage.py migrate
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

## Acesso protegido

Por padrão, o MVP é destinado ao uso local. Para exigir autenticação:

1. Defina `APP_REQUIRE_LOGIN=True` no `.env`.
2. Crie um usuário administrativo:

```bash
docker compose exec app python manage.py createsuperuser
```

Se a aplicação for exposta à internet, também use HTTPS por meio de um proxy reverso, mantenha `DJANGO_DEBUG=False` e restrinja `DJANGO_ALLOWED_HOSTS`.

## Dados e backups

- `data/db.sqlite3`: banco local fora do Git.
- `/backup/`: baixa uma cópia consistente do banco pelo navegador.
- `/exportar/csv/`: exporta o histórico em formato tabular.
- `.env`: configuração local e segredos, ignorados pelo Git.

O repositório é público. Não publique o banco SQLite, exportações da planilha ou arquivos de backup.

## Testes

```bash
python manage.py test
python manage.py check
```

## Estrutura

```text
config/                 Configuração do Django
fuelings/               Modelos, cálculos, telas e importadores
templates/              Interface HTML
static/                 Estilos da aplicação
scripts/entrypoint.sh    Inicialização do container
compose.yaml             Serviço único e volume SQLite
```
