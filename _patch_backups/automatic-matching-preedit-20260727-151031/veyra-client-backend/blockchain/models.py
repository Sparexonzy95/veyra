from django.db import models

class IndexerCursor(models.Model):
    chain_id = models.PositiveBigIntegerField()
    contract_address = models.CharField(max_length=42)
    last_scanned_block = models.PositiveBigIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['chain_id', 'contract_address'], name='uniq_indexer_cursor')]
