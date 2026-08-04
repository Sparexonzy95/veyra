from django.core.management.base import BaseCommand
from blockchain.indexer import scan_once

class Command(BaseCommand):
    help = 'Index VeyraJobEscrow events from Arc Testnet.'

    def add_arguments(self, parser):
        parser.add_argument('--to-block', type=int, default=None)
        parser.add_argument('--chunk-size', type=int, default=1000)

    def handle(self, *args, **options):
        result = scan_once(to_block=options['to_block'], chunk_size=options['chunk_size'])
        self.stdout.write(self.style.SUCCESS(str(result)))
