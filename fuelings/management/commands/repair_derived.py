from django.core.management.base import BaseCommand, CommandError
from django.db import models

from fuelings.models import Fueling
from fuelings.services import DERIVED_FIELDS, DerivedValueOutOfRange, get_default_vehicle, recalculate_all


class Command(BaseCommand):
    help = (
        "Recupera o banco quando um valor calculado fora da faixa impede a leitura do histórico "
        "(todas as telas com erro 500). Limpa as colunas derivadas e recalcula a sequência."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            type=int,
            metavar="ID",
            help="Exclui o abastecimento com este ID antes de recalcular (use o ID indicado pelo próprio comando).",
        )

    def handle(self, *args, **options):
        # UPDATE direto, sem ler as linhas: a leitura é justamente o que falha.
        blank = {
            name: "" if isinstance(Fueling._meta.get_field(name), models.CharField) else None
            for name in DERIVED_FIELDS
        }
        cleared = Fueling.objects.update(**blank)
        self.stdout.write(f"Colunas calculadas limpas em {cleared} abastecimentos.")

        if options["delete"] is not None:
            deleted, _ = Fueling.objects.filter(pk=options["delete"]).delete()
            if not deleted:
                raise CommandError(f"Abastecimento {options['delete']} não encontrado.")
            self.stdout.write(f"Abastecimento {options['delete']} excluído.")

        try:
            recalculate_all(get_default_vehicle())
        except DerivedValueOutOfRange as error:
            # As colunas continuam limpas (o recálculo é atômico), então o registro já pode
            # ser aberto e corrigido pela tela de edição.
            raise CommandError(
                f"{error.message}\n"
                f"Corrija o registro em /abastecimentos/{error.row_id}/editar/ ou exclua-o com:\n"
                f"  python manage.py repair_derived --delete {error.row_id}"
            ) from error
        self.stdout.write(self.style.SUCCESS("Sequência recalculada. O histórico voltou a ser legível."))
